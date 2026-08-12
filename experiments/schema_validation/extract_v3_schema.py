"""Schema validation: can the v2 schema actually extract across paper types?

PURPOSE: not quality, not gold — feasibility. Does the schema work at all?
We have NEVER actually extracted with this schema. Prior "validation" was
keyword regex hits, which is near-meaningless. This is the first real test.

WHAT WE LEARN (the only point):
  - Which L3 subtypes / elements actually get extracted vs are empty.
  - Where the schema is ambiguous (extractor produces messy/empty results).
  - Whether L1/L2/L3 layering survives contact with real papers.

WHAT WE DO NOT LEARN:
  - Whether the schema is correct (need expert + gold for that).
  - Extraction quality vs gold (no gold exists yet).

DESIGN:
  - 10 papers, deliberately spanning types: rheology / experiment / DEM /
    theory / review / kinetic-theory / silo / drag / nonlocal / shape-competing.
  - One extractor (deepseek-chat), temperature 0.
  - v2 schema (L1 entities + L2 relations + L3 higher-order, FUNCTION_RELATION-centric as currently in DESIGN-v1.md).
  - Record: per paper, what was extracted at each layer. No verifier.
  - Output: raw atoms + a coverage table (which L3 elements appeared per paper).

KILL POINTS (what would mean schema design is broken):
  - L3 empty on >50% of papers -> L3 schema doesn't match what papers contain.
  - Extractor emits non-JSON / garbage on >30% -> schema too complex to instruct.
  - Same paper extracted differently across runs (determinism check) -> schema ambiguous.

This is a FEASIBILITY probe, not a study. n=10, single seed. Conclusions are
directional only.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.abspath(os.path.join(HERE, "..", ".."))
TMP = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark")
MINERU_BASE = "C:/Users/D0n9/Desktop/science_evo/data/upstream/remote_mineru/mineru_2355/papers"
OUT = os.path.join(TMP, "schema_validation_v3_results.jsonl")

# read env from era worktree (benchmark worktree has no .env)
ENV = {}
for _line in open("C:/Users/D0n9/Desktop/LogicKG/.env", encoding="utf-8"):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        ENV[_k.strip()] = _v.strip().strip('"').strip("'")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

MODEL = "deepseek-chat"
BASE = "https://api.deepseek.com/v1"
KEY = ENV.get("DEEPSEEK_API_KEY")

SCHEMA_V2 = """Schema (three-tier, v3 — contribution-centric):

L1 entities: MATERIAL, SAMPLE, DEVICE, NUMERIC, UNIT, PROPERTY, MEASUREMENT, CONDITION.
L2 relations: measures_property, property_value, condition_environment, condition_sampleFeatures, condition_instrument, taken_from.
L3 contribution layer (reified first-class entities, NOT edges):
  - RESEARCH_QUESTION (the paper's research question).
  - CONTRIBUTION (a reified first-class entity = the paper's core scientific contribution). Has multi-label subtypes (a contribution can have MORE THAN ONE):
    constitutive_law (a constitutive/scaling law or formula, e.g. mu(I)=...)
    experimental_finding (an experimental observation/result, e.g. "drag increases with velocity")
    mechanism_analysis (an explanation of WHY, e.g. "elastic modulus determined by stress level")
    theoretical_result (a derived equation/stability/proof, e.g. well-posedness)
    numerical_finding (a DEM/simulation-discovered result)
    integrative (cross-method synthesis)
  - CONTRIBUTION_RELATION (a directed edge BETWEEN contributions): supports | conflicts | depends_on | applies_in | derives_from. May carry qualifier (condition/regime/range).
Paper-level: paper_type = rheology | experiment | theory | DEM | review | other.

CRITICAL: do NOT stuff experimental observations into constitutive_law. If a contribution is an experimental measurement/observation (not a formula), use experimental_finding. If it is a WHY-explanation, use mechanism_analysis. Only use constitutive_law for actual formulas/laws.

Output a JSON array of atoms. Mark layer:
L1: {"layer":"L1","entity_type":"...","entity":"..."}
L2: {"layer":"L2","relation":"...","subject":"...","object":"...","conditions":[...]}
L3 CONTRIBUTION: {"layer":"L3","type":"CONTRIBUTION","statement":"...","subtypes":["constitutive_law",...]}
L3 RELATION: {"layer":"L3","type":"CONTRIBUTION_RELATION","from":"(contribution stmt or id)","relation":"supports|conflicts|...","to":"(contribution stmt or id)","qualifier":"..."}
L3 RQ: {"layer":"L3","type":"RESEARCH_QUESTION","statement":"..."}
Paper: {"layer":"PAPER","paper_type":"..."}"""

PROMPT = """Extract structured information from this granular flow paper.

{schema}

PAPER TEXT:
{text}

Extract ALL atoms across L1/L2/L3 + one PAPER-level atom. Output ONLY a JSON array."""


def _call(prompt: str, max_tokens: int = 4000) -> str | None:
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }).encode()
    for _ in range(3):
        try:
            req = urllib.request.Request(
                BASE + "/chat/completions",
                data=body,
                headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            )
            raw = urllib.request.urlopen(req, context=CTX, timeout=180).read()
            return json.loads(raw)["choices"][0]["message"]["content"]
        except Exception:
            continue
    return None


def _parse(text: str | None):
    if not text:
        return None
    text = re.sub(r"```json|```", "", text, flags=re.S)
    m = re.search(r"(\[.*\])", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _load_text(paper_id: str, max_chars: int = 10000) -> str:
    p = os.path.join(MINERU_BASE, paper_id, "content_list.json")
    if not os.path.isfile(p):
        return ""
    cl = json.load(open(p, encoding="utf-8"))
    return " ".join(it.get("text", "") for it in cl if it.get("type") == "text")[:max_chars]


# 10 papers spanning types (already verified to exist in mineru_2355)
SAMPLES = [
    ("rheology-muI", "PPR_B0E8916D4E19"),       # Jop 2006
    ("elasticity", "PPR_01E97B53AF38"),           # Agnolin 2007
    ("experiment-drag", "PPR_692722FBA788"),      # Albert 1999
    ("DEM-industrial", "PPR_65BCF653FEF9"),       # Cleary 2002
    ("theory-stability", "PPR_A3D5B1EC1032"),     # Alam 1998
    ("kinetic-theory", "PPR_D6A96452F9E8"),       # Berzi 2014
    ("silo-experiment", "PPR_3CF23B633C4F"),      # Choi 2005
    ("scaling-rheology", "PPR_9F45D6625A0F"),     # Kim 2020
    ("nonlocal-shearzone", "PPR_D1B4FB59063B"),  # Fenistein 2003 Wide shear zones
    ("review-geophys", "PPR_5DCD02341AA6"),  # Mehta 1994 Granular Matter (review-ish)
]


def _run_one(label: str, paper_id: str) -> dict:
    text = _load_text(paper_id)
    if not text:
        return {"label": label, "paper_id": paper_id, "stage": "no_text"}
    raw = _call(PROMPT.format(schema=SCHEMA_V2, text=text))
    atoms = _parse(raw)
    if not isinstance(atoms, list):
        return {"label": label, "paper_id": paper_id, "stage": "parse_fail", "raw": (raw or "")[:200]}

    # coverage: which layers/elements appeared
    layers = {}
    l3_types = {}
    contribution_subtypes = {}  # count per subtype
    contrib_relation_types = {}
    paper_type = None
    for a in atoms:
        if not isinstance(a, dict):
            continue
        layer = a.get("layer", "?")
        layers[layer] = layers.get(layer, 0) + 1
        if layer == "L3":
            t = a.get("type", "?")
            l3_types[t] = l3_types.get(t, 0) + 1
            if t == "CONTRIBUTION":
                for st in (a.get("subtypes") or [a.get("subtype")] or []):
                    if st:
                        contribution_subtypes[st] = contribution_subtypes.get(st, 0) + 1
            if t == "CONTRIBUTION_RELATION":
                rel = a.get("relation", "?")
                contrib_relation_types[rel] = contrib_relation_types.get(rel, 0) + 1
        if layer == "PAPER":
            paper_type = a.get("paper_type")

    return {
        "label": label,
        "paper_id": paper_id,
        "stage": "done",
        "n_atoms": len(atoms),
        "layers": layers,
        "l3_types": l3_types,
        "contribution_subtypes": contribution_subtypes,
        "contrib_relation_types": contrib_relation_types,
        "paper_type_inferred": paper_type,
    }


def main() -> None:
    if not KEY:
        raise SystemExit("no DEEPSEEK_API_KEY")
    print(f"samples: {len(SAMPLES)} | model: {MODEL} | schema: v3 (contribution-centric)")
    print("feasibility probe — does the schema extract at all? (not quality)")
    print()

    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_run_one, lbl, pid): lbl for lbl, pid in SAMPLES}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            if r.get("stage") == "done":
                print(f"  [{r['label']}] n={r['n_atoms']} layers={r['layers']} l3={r['l3_types']} contrib_sub={r['contribution_subtypes']} rels={r['contrib_relation_types']} ptype={r['paper_type_inferred']}")
            else:
                print(f"  [{r['label']}] {r.get('stage')}")

    with open(OUT, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # coverage table
    print("\n=== COVERAGE TABLE ===")
    print(f"{'paper':<22}{'n':>4}{'L1':>4}{'L2':>4}{'L3':>4}{'PAPER':>6}  contribution_subtypes  rels  paper_type")
    for r in results:
        if r.get("stage") != "done":
            print(f"{r['label']:<22}  -- {r.get('stage')}")
            continue
        L = r["layers"]
        print(f"{r['label']:<22}{r['n_atoms']:>4}{L.get('L1',0):>4}{L.get('L2',0):>4}{L.get('L3',0):>4}{L.get('PAPER',0):>6}  {r['contribution_subtypes']}  {r['contrib_relation_types']}  {r['paper_type_inferred']}")

    # kill-point checks
    print("\n=== KILL POINTS ===")
    done = [r for r in results if r.get("stage") == "done"]
    n = len(done)
    l3_empty = sum(1 for r in done if r["layers"].get("L3", 0) == 0)
    print(f"papers with L3 empty: {l3_empty}/{n}  (kill if >50%)")
    total_atoms = sum(r["n_atoms"] for r in done)
    print(f"total atoms extracted: {total_atoms}  (across {n} papers)")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
