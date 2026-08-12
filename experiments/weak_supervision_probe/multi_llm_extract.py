"""Weak-supervision feasibility: do multiple LLMs agree when extracting with schema v3?

PURPOSE: before implementing the full 3-method weak-supervision pipeline (A1/A2/A3 +
fusion), verify feasibility on a small scale. If 4 LLMs produce wildly inconsistent
extractions, fusion rules won't save it — the schema is too ambiguous or the task
too hard. If they broadly agree, fusion is worth building.

WHAT WE LEARN:
  - atom-count consistency across LLMs (does one extract 5x another?)
  - schema-v3 comprehension consistency (do all use L3 CONTRIBUTION + subtypes correctly?)
  - content overlap (Jaccard on L1 entities + L3 statements) — drives fusion rule design.

WHAT WE DON'T LEARN:
  - correctness (no gold).
  - which LLM is "best" (no gold to judge against).

DESIGN:
  - 10 papers from the 1186 purified corpus, spanning subdomains.
  - 4 LLMs: deepseek-chat, Kimi-K2.6, GLM-5-Turbo, Qwen3.5-27B (different providers).
  - Same schema v3 prompt (from the formal JSON Schema).
  - Compare per-paper: atom count, layer distribution, L3 subtype usage, entity overlap.

KILL POINTS:
  - If any LLM produces garbage/non-JSON on >50% papers -> that LLM can't follow schema.
  - If atom counts vary >5x across LLMs on the same paper -> schema too ambiguous.
  - If L3 empty on >50% for any LLM -> that LLM can't do higher-order extraction.
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
PURIFIED = os.path.join(TMP, "purified_corpus_1186.jsonl")
MINERU_BASE = "C:/Users/D0n9/Desktop/science_evo/data/upstream/remote_mineru/mineru_2355/papers"
OUT = os.path.join(TMP, "multi_llm_extract_results.jsonl")

ENV = {}
for _line in open("C:/Users/D0n9/Desktop/LogicKG/.env", encoding="utf-8"):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        ENV[_k.strip()] = _v.strip().strip('"').strip("'")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

EP = {
    "deepseek": ("https://api.deepseek.com/v1", ENV.get("DEEPSEEK_API_KEY"), "deepseek-chat"),
    "kimi": (ENV.get("PARATERA_BASE_URL", ""), ENV.get("PARATERA_API_KEY"), "Kimi-K2.6"),
    "glm": (ENV.get("PARATERA_BASE_URL", ""), ENV.get("PARATERA_API_KEY"), "GLM-5-Turbo"),
    "qwen": (ENV.get("PARATERA_BASE_URL", ""), ENV.get("PARATERA_API_KEY"), "Qwen3.5-27B"),
}

SCHEMA_PROMPT = """Extract structured information from this granular flow paper using schema v3.

Schema (three-tier, contribution-centric):

L1 entities: MATERIAL, SAMPLE, DEVICE, NUMERIC, UNIT, PROPERTY, MEASUREMENT, CONDITION.
L2 relations: measures_property, property_value, condition_environment, condition_sampleFeatures, condition_instrument, taken_from.
L3 (contribution layer — reified first-class entities, NOT edges):
  - CONTRIBUTION: a paper's core scientific contribution. Has multi-label subtypes (can have >1):
    constitutive_law (a formula/law, e.g. mu(I)=...)
    experimental_finding (an experimental observation, e.g. "drag increases with velocity")
    mechanism_analysis (a WHY explanation, e.g. "elastic modulus determined by stress")
    theoretical_result (a derived equation/stability/proof)
    numerical_finding (a DEM/simulation result)
    integrative (cross-method synthesis)
  - CONTRIBUTION_RELATION: directed edge between contributions: supports | conflicts | depends_on | applies_in | derives_from. May carry qualifier.
  - RESEARCH_QUESTION: the paper's research question.
Paper-level: paper_type = rheology | experiment | theory | DEM | review | other.

CRITICAL: do NOT stuff experimental observations into constitutive_law. Use experimental_finding for observations, mechanism_analysis for explanations.

Output ONLY a JSON array of atoms:
L1: {"layer":"L1","entity_type":"...","entity":"..."}
L2: {"layer":"L2","relation":"...","subject":"...","object":"...","conditions":[...]}
L3 CONTRIBUTION: {"layer":"L3","type":"CONTRIBUTION","statement":"...","subtypes":["..."],"params":[...]}
L3 RELATION: {"layer":"L3","type":"CONTRIBUTION_RELATION","relation":"...","from":"...","to":"...","qualifier":"..."}
L3 RQ: {"layer":"L3","type":"RESEARCH_QUESTION","statement":"..."}
PAPER: {"layer":"PAPER","paper_type":"..."}

PAPER TEXT:
{text}"""


def _call(ep: str, text: str) -> str | None:
    base, key, model = EP[ep]
    if not key:
        return None
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": SCHEMA_PROMPT.replace("{text}", text)}],
        "temperature": 0.0,
        "max_tokens": 4000,
    }).encode()
    for _ in range(2):
        try:
            req = urllib.request.Request(
                base.rstrip("/") + "/chat/completions",
                data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
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


def _load_text(paper_id: str, max_chars: int = 9000) -> str:
    p = os.path.join(MINERU_BASE, paper_id, "content_list.json")
    if not os.path.isfile(p):
        return ""
    cl = json.load(open(p, encoding="utf-8"))
    return " ".join(it.get("text", "") for it in cl if it.get("type") == "text")[:max_chars]


def _stats(atoms):
    if not isinstance(atoms, list):
        return {"n": 0, "layers": {}, "l3_types": {}, "subtypes": {}, "entities": set(), "contrib_stmts": set()}
    layers = {}
    l3_types = {}
    subtypes = {}
    entities = set()
    contrib_stmts = set()
    for a in atoms:
        if not isinstance(a, dict):
            continue
        L = a.get("layer", "?")
        layers[L] = layers.get(L, 0) + 1
        if L == "L1":
            e = (a.get("entity") or "").lower().strip()
            if e:
                entities.add(e[:60])
        if L == "L3":
            t = a.get("type", "?")
            l3_types[t] = l3_types.get(t, 0) + 1
            if t == "CONTRIBUTION":
                s = (a.get("statement") or "").lower().strip()
                if s:
                    contrib_stmts.add(s[:80])
                for st in (a.get("subtypes") or []):
                    subtypes[st] = subtypes.get(st, 0) + 1
    return {"n": len(atoms), "layers": layers, "l3_types": l3_types, "subtypes": subtypes,
            "entities": entities, "contrib_stmts": contrib_stmts}


def main():
    purified = [json.loads(l) for l in open(PURIFIED, encoding="utf-8") if l.strip()]
    # 10 papers spanning subdomains
    by_sub = {}
    for r in purified:
        s = r.get("subdomain", "other")
        by_sub.setdefault(s, []).append(r)
    sample = []
    for s in ["rheology", "experiment", "theory", "DEM", "geophysical", "simulation"]:
        sample.extend(by_sub.get(s, [])[:2])
    sample = sample[:10]
    print(f"sample: {len(sample)} papers | LLMs: {list(EP)}", flush=True)
    # clear old results
    if os.path.exists(OUT):
        os.remove(OUT)
    print()

    results = []
    for r in sample:
        pid = r["paper_id"]
        text = _load_text(pid)
        if not text:
            continue
        per_llm = {}
        # 4 LLMs in parallel per paper (not serial — that was 20+ min)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {pool.submit(_call, ep, text): ep for ep in EP}
            for fut in as_completed(futs):
                ep = futs[fut]
                raw = fut.result()
                atoms = _parse(raw)
                st = _stats(atoms)
                st["entities"] = sorted(st["entities"])
                st["contrib_stmts"] = sorted(st["contrib_stmts"])
                per_llm[ep] = st
                print(f"    {ep:<10} n={st['n']:>3} L={st['layers']} L3={st['l3_types']} sub={st['subtypes']}", flush=True)
        rec = {"paper_id": pid, "title": r.get("title", "")[:60], "subdomain": r.get("subdomain"), "per_llm": per_llm}
        results.append(rec)
        print(f"  [{r.get('subdomain','?')}] {pid} done", flush=True)
        # incremental save (don't lose progress on crash)
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print()

    with open(OUT, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # cross-LLM consistency
    print("=== CROSS-LLM CONSISTENCY ===")
    for r in results:
        p = r["per_llm"]
        counts = [p[e]["n"] for e in EP if p.get(e)]
        if len(counts) >= 2:
            ratio = max(counts) / max(min(counts), 1)
            # entity Jaccard between first two LLMs with data
            ents = [set(p[e]["entities"]) for e in EP if p.get(e) and p[e]["entities"]]
            if len(ents) >= 2:
                inter = len(ents[0] & ents[1])
                union = len(ents[0] | ents[1])
                jac = inter / union if union else 0
            else:
                jac = -1
            print(f"  {r['paper_id']}: max/min atom ratio={ratio:.1f} | entity Jaccard(LLM0vsLLM1)={jac:.2f}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
