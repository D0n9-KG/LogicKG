"""Diagnose v3 schema on rheology papers — does it actually capture μ(I) and regime?

PURPOSE: LLM-expert review claimed 3 load-bearing problems:
  1. μ(I) multi-variable closure doesn't fit (no CLOSURE entity)
  2. regime (quasi-static/dense/collisional) has no slot
  3. CONDITION mixes boundary/initial/material-param/regime

This test checks whether those problems are REAL by extracting on 3 rheology
papers and inspecting what the schema actually produces — not just counts,
but the raw L3 atoms, to see if μ(I) and regime are captured or lost.

3 papers (all classic granular flow rheology):
  - Jop 2006 (μ(I) constitutive law, the foundational paper)
  - Kharel 2017 (partial jamming + non-locality)
  - Pouliquen 2004 (velocity correlations / rheology)

WHAT WE LOOK FOR (per agent's claims):
  - Is μ(I) law captured as a CONTRIBUTION? Can its multi-variable structure be seen?
  - Are regime labels (dense/quasi-static/collisional) captured anywhere? Where?
  - Are boundary/initial/material-params distinguished, or all crammed in CONDITION?

This is DIAGNOSTIC, not statistical. We read the actual atoms.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.abspath(os.path.join(HERE, "..", ".."))
TMP = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark")
MINERU_BASE = "C:/Users/D0n9/Desktop/science_evo/data/upstream/remote_mineru/mineru_2355/papers"
OUT = os.path.join(TMP, "v3_rheology_diagnosis.jsonl")

ENV = {}
for _line in open("C:/Users/D0n9/Desktop/LogicKG/.env", encoding="utf-8"):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        ENV[_k.strip()] = _v.strip().strip('"').strip("'")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

PAPERS = [
    ("Jop 2006 mu(I)", "PPR_B0E8916D4E19"),
    ("Kharel 2017 jamming+nonlocal", "PPR_B1E961932B43"),
    ("Pouliquen 2004 rheology", "PPR_265FEBC5DCF1"),
]

SCHEMA_V3 = """Schema (three-tier, v3, contribution-centric):

L1 entities: MATERIAL, SAMPLE, DEVICE, NUMERIC, UNIT, PROPERTY, MEASUREMENT, CONDITION.
L2 relations: measures_property, property_value, condition_environment, condition_sampleFeatures, condition_instrument, taken_from.
L3 (contribution layer — reified first-class entities, NOT edges):
  - CONTRIBUTION: paper's core scientific contribution. Multi-label subtypes (can have >1):
    constitutive_law | experimental_finding | mechanism_analysis | theoretical_result | numerical_finding | integrative
  - CONTRIBUTION_RELATION: directed edge between contributions: supports | conflicts | depends_on | applies_in | derives_from
  - RESEARCH_QUESTION: the paper's research question.
Paper-level: paper_type = rheology | experiment | theory | DEM | review | other.

Output ONLY a JSON array of atoms.
L1: {"layer":"L1","entity_type":"...","entity":"..."}
L2: {"layer":"L2","relation":"...","subject":"...","object":"...","conditions":[...]}
L3 CONTRIBUTION: {"layer":"L3","type":"CONTRIBUTION","statement":"...","subtypes":["..."],"params":[...]}
L3 RELATION: {"layer":"L3","type":"CONTRIBUTION_RELATION","relation":"...","from":"...","to":"...","qualifier":"..."}
L3 RQ: {"layer":"L3","type":"RESEARCH_QUESTION","statement":"..."}
PAPER: {"layer":"PAPER","paper_type":"..."}"""

PROMPT = """Extract from this granular flow paper.

{schema}

PAPER TEXT:
{text}

Output ONLY a JSON array of atoms."""


def _call(text):
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": PROMPT.format(schema=SCHEMA_V3, text=text)}],
        "temperature": 0.0,
        "max_tokens": 4000,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {ENV['DEEPSEEK_API_KEY']}", "Content-Type": "application/json"},
    )
    raw = urllib.request.urlopen(req, context=CTX, timeout=180).read()
    return json.loads(raw)["choices"][0]["message"]["content"]


def _parse(text):
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


def _load(pid, max_chars=12000):
    p = os.path.join(MINERU_BASE, pid, "content_list.json")
    if not os.path.isfile(p):
        return ""
    cl = json.load(open(p, encoding="utf-8"))
    return " ".join(it.get("text", "") for it in cl if it.get("type") == "text")[:max_chars]


def main():
    results = []
    for label, pid in PAPERS:
        text = _load(pid)
        if not text:
            print(f"[{label}] no text", flush=True)
            continue
        raw = _call(text)
        atoms = _parse(raw)
        if not isinstance(atoms, list):
            print(f"[{label}] parse fail", flush=True)
            continue

        # diagnose: print ALL L3 atoms + CONDITION entities (the claimed problem areas)
        print(f"\n{'='*70}", flush=True)
        print(f"[{label}] {pid} — {len(atoms)} atoms", flush=True)
        print(f"{'='*70}", flush=True)

        print(f"\n--- L3 CONTRIBUTION atoms (does μ(I) law appear? as what?) ---", flush=True)
        for a in atoms:
            if isinstance(a, dict) and a.get("layer") == "L3" and a.get("type") == "CONTRIBUTION":
                print(f"  [{','.join(a.get('subtypes',[]))}] {a.get('statement','')[:120]}", flush=True)
                if a.get("params"):
                    print(f"    params: {a.get('params')}", flush=True)

        print(f"\n--- L3 CONTRIBUTION_RELATION (conflicts? applies_in? regime?) ---", flush=True)
        for a in atoms:
            if isinstance(a, dict) and a.get("layer") == "L3" and a.get("type") == "CONTRIBUTION_RELATION":
                print(f"  {a.get('relation','?')}: {a.get('from','')[:40]} -> {a.get('to','')[:40]} | q={a.get('qualifier','')[:40]}", flush=True)

        print(f"\n--- CONDITION entities (are boundary/initial/material-param/regime mixed?) ---", flush=True)
        conds = [a for a in atoms if isinstance(a, dict) and a.get("layer") == "L1" and a.get("entity_type") == "CONDITION"]
        for a in conds:
            print(f"  {a.get('entity','')[:80]}", flush=True)

        print(f"\n--- regime keywords in paper (dense/quasi-static/collisional/inertial) ---", flush=True)
        for kw in ["quasi-static", "dense", "collisional", "inertial", "regime"]:
            n = len(re.findall(kw, text, re.I))
            if n:
                print(f"  '{kw}' appears {n} times in text", flush=True)

        rec = {"label": label, "paper_id": pid, "n_atoms": len(atoms),
               "n_l3_contrib": sum(1 for a in atoms if isinstance(a,dict) and a.get("layer")=="L3" and a.get("type")=="CONTRIBUTION"),
               "n_l3_rel": sum(1 for a in atoms if isinstance(a,dict) and a.get("layer")=="L3" and a.get("type")=="CONTRIBUTION_RELATION"),
               "n_conditions": len(conds)}
        results.append(rec)

    with open(OUT, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nwrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
