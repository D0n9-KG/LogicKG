"""Corpus purification via LLM title classification.

WHY: keyword filter (granular|DEM >=10) is unreliable (misses "dense suspension/
powder/shear band" papers; false-hits "granular computing"). 2355 manifest has
NO citation-layer info (reference_depth all 0) and NO abstract (0% fill) — only
title (100%) is available. So purification must use LLM semantic judgment on titles.

DESIGN:
  - Sample 200 papers from the 2355 (stratified to span the corpus, not just first 200).
  - LLM (deepseek-chat, temp 0) classifies each title:
      is_granular_flow: yes | no | unclear
      subdomain: rheology | experiment | theory | DEM | simulation | geophysical | other | n/a
      confidence: high | medium | low
  - No keyword matching. Pure semantic.
  - Report: purity = yes/total; subdomain distribution; unclear rate.

KILL POINTS (fixed before running):
  - If unclear >30% -> titles lack signal; need to fetch abstracts first.
  - If yes purity <40% -> corpus is too diluted for a granular-flow benchmark;
    need to re-pull from the 10447 survey corpus instead.
  - If yes purity >80% -> good enough; proceed to full 2355 classification.

Output: per-paper classification + aggregate stats.
"""

from __future__ import annotations

import json
import os
import random
import re
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.abspath(os.path.join(HERE, "..", ".."))
TMP = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark")
MANIFEST = "C:/Users/D0n9/Desktop/science_evo/data/upstream/remote_mineru/mineru_2355/paper_manifest.jsonl"
OUT = os.path.join(TMP, "title_classification_200.jsonl")

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
N_SAMPLE = int(os.environ.get("N_SAMPLE", "200"))
SEED = 4711

PROMPT = """Classify this scientific paper title.

Is this paper about GRANULAR FLOW / granular materials / powder mechanics / dense suspensions / rheology of particulate media (the physics of granular materials and their flows)?

TITLE: {title}

Answer ONLY valid JSON:
{{"is_granular_flow": "yes" or "no" or "unclear", "subdomain": "rheology" or "experiment" or "theory" or "DEM" or "simulation" or "geophysical" or "other" or "n/a", "confidence": "high" or "medium" or "low", "reason": "one short phrase"}}

Note: "granular computing" (a CS subfield) is NOT granular flow — answer no. "Granular" in the sense of particulate physical material IS granular flow."""


def _call(title: str) -> dict | None:
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT.format(title=title)}],
        "temperature": 0.0,
        "max_tokens": 150,
    }).encode()
    for _ in range(3):
        try:
            req = urllib.request.Request(
                BASE + "/chat/completions",
                data=body,
                headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            )
            raw = urllib.request.urlopen(req, context=CTX, timeout=60).read()
            text = json.loads(raw)["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                return json.loads(m.group(0))
        except Exception:
            continue
    return None


def main() -> None:
    if not KEY:
        raise SystemExit("no DEEPSEEK_API_KEY")
    man = [json.loads(l) for l in open(MANIFEST, encoding="utf-8") if l.strip()]
    rng = random.Random(SEED)
    rng.shuffle(man)
    sample = man[:N_SAMPLE]
    print(f"sample: {len(sample)} from {len(man)} | model: {MODEL}")
    print("kill points: unclear>30% -> need abstract; yes<40% -> corpus too diluted; yes>80% -> good")
    print()

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_call, (r.get("title") or "")[:200]): r for r in sample}
        for i, fut in enumerate(as_completed(futs), 1):
            r = futs[fut]
            cls = fut.result()
            rec = {"paper_id": r.get("paper_id"), "title": r.get("title", "")[:100], "classification": cls}
            results.append(rec)
            if i % 40 == 0:
                print(f"  {i}/{len(sample)} done", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # aggregate
    yes = no = unclear = 0
    subs = {}
    confs = {}
    parsed = 0
    for r in results:
        c = r.get("classification") or {}
        if not c:
            continue
        parsed += 1
        v = c.get("is_granular_flow", "?")
        if v == "yes":
            yes += 1
        elif v == "no":
            no += 1
        else:
            unclear += 1
        s = c.get("subdomain", "?")
        subs[s] = subs.get(s, 0) + 1
        cf = c.get("confidence", "?")
        confs[cf] = confs.get(cf, 0) + 1

    print("\n=== PURIFICATION RESULT ===")
    print(f"parsed: {parsed}/{len(results)}")
    print(f"yes (granular flow):    {yes} ({yes/max(parsed,1)*100:.0f}%)")
    print(f"no:                     {no} ({no/max(parsed,1)*100:.0f}%)")
    print(f"unclear:                {unclear} ({unclear/max(parsed,1)*100:.0f}%)")
    print(f"\nsubdomains: {dict(sorted(subs.items(), key=lambda x:-x[1]))}")
    print(f"confidence: {dict(sorted(confs.items(), key=lambda x:-x[1]))}")
    print(f"\n=== KILL POINTS ===")
    if unclear / max(parsed, 1) > 0.30:
        print(f"  KILL: unclear {unclear/parsed*100:.0f}% > 30% -> titles lack signal, fetch abstracts")
    if yes / max(parsed, 1) < 0.40:
        print(f"  KILL: yes {yes/parsed*100:.0f}% < 40% -> corpus too diluted, repull from 10447")
    if yes / max(parsed, 1) > 0.80:
        print(f"  PASS: yes {yes/parsed*100:.0f}% > 80% -> good, proceed to full 2355")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
