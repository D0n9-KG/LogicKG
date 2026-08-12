"""MARY fusion test: is semantic-neighborhood inclusion better than raw union?

CONTEXT: multi-LLM extraction showed entity Jaccard 0.09-0.46 (low overlap).
Raw union would keep everything (noise explosion); majority vote loses valid
atoms. MARY (ACL 2026.findings-acl.599) proposes: include a minority atom
(only 1 LLM extracted it) only if its context embedding is close to the
majority atoms (those both LLMs extracted). This tests that rule.

INPUT: existing 10-paper multi-LLM results (entities + contrib_stmts per LLM).
We use Kimi + Qwen (both stable, 10/10 success) — DeepSeek/GLM dropped.

METHOD:
  1. For each paper, take Kimi entities ∪ Qwen entities.
  2. Majority = entities in BOTH. Minority = entities in only ONE.
  3. For each minority entity, compute embedding similarity to majority set (max cosine).
  4. If similarity > threshold -> KEEP (MARY rule). Else -> flag as candidate noise.
  5. Compare: raw union count vs MARY-filtered count, and how many minority atoms survive.

LIMITATION (honest):
  - No gold to measure precision/recall. We can only measure "how much does MARY
    prune vs union" and "is the pruning sensible" (manual spot-check).
  - Embeddings: sentence-transformers if available, else char-overlap fallback.
  - n=10, 2 LLMs (Kimi+Qwen). Directional only.

WHAT WE LEARN:
  - Does MARY prune a meaningful fraction of minority atoms? (If 0% pruned, rule useless.)
  - Is the pruning directionally sensible? (Spot-check a few.)
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(os.path.abspath(os.path.join(HERE, "..", "..")), ".research_tmp", "granular-benchmark")
IN = os.path.join(TMP, "multi_llm_extract_results.jsonl")
OUT = os.path.join(TMP, "mary_fusion_results.jsonl")

# embeddings via Paratera GLM-Embedding-2 API (no local install needed)
ENV = {}
for _line in open("C:/Users/D0n9/Desktop/LogicKG/.env", encoding="utf-8"):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        ENV[_k.strip()] = _v.strip().strip('"').strip("'")

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_EMB_BASE = ENV.get("PARATERA_BASE_URL", "").rstrip("/")
_EMB_KEY = ENV.get("PARATERA_API_KEY", "")
_EMB_MODEL = "GLM-Embedding-2"

import math


def _embed_batch(texts, batch=32):
    """Call GLM-Embedding-2 API, return list of embedding vectors."""
    if not texts:
        return []
    out = []
    for i in range(0, len(texts), batch):
        chunk = texts[i:i+batch]
        body = json.dumps({"model": _EMB_MODEL, "input": chunk}).encode()
        req = urllib.request.Request(
            _EMB_BASE + "/embeddings",
            data=body,
            headers={"Authorization": f"Bearer {_EMB_KEY}", "Content-Type": "application/json"},
        )
        raw = urllib.request.urlopen(req, context=_CTX, timeout=60).read()
        data = json.loads(raw).get("data", [])
        data.sort(key=lambda x: x.get("index", 0))
        out.extend([d["embedding"] for d in data])
    return out


def _cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _sim_matrix(minority, majority):
    """Return max-cosine-similarity of each minority item to majority set (via API embeddings)."""
    if not majority or not minority:
        return [0.0] * len(minority)
    all_texts = list(minority) + list(majority)
    embs = _embed_batch(all_texts)
    n_min = len(minority)
    min_embs = embs[:n_min]
    maj_embs = embs[n_min:]
    max_sims = []
    for me in min_embs:
        best = max(_cosine(me, mje) for mje in maj_embs)
        max_sims.append(best)
    return max_sims


def main():
    rows = [json.loads(l) for l in open(IN, encoding="utf-8") if l.strip()]
    # only papers where both kimi and qwen succeeded (n>0)
    papers = []
    for r in rows:
        pl = r.get("per_llm", {})
        kimi = pl.get("kimi", {})
        qwen = pl.get("qwen", {})
        if kimi.get("n", 0) > 0 and qwen.get("n", 0) > 0:
            papers.append((r["paper_id"], set(kimi.get("entities", [])), set(qwen.get("entities", []))))

    print(f"papers with both kimi+qwen success: {len(papers)}")
    print()

    THRESHOLDS = [0.3, 0.5, 0.7]
    results = []

    for pid, kimi_ents, qwen_ents in papers:
        union = kimi_ents | qwen_ents
        majority = kimi_ents & qwen_ents
        minority_kimi = kimi_ents - qwen_ents  # only kimi
        minority_qwen = qwen_ents - kimi_ents  # only qwen
        all_minority = list(minority_kimi) + list(minority_qwen)
        majority_list = list(majority)

        if not all_minority:
            print(f"  {pid}: no minority atoms (full agreement) — union={len(union)}", flush=True)
            results.append({"paper_id": pid, "union": len(union), "majority": len(majority),
                            "minority": 0, "mary_kept": 0, "mary_pruned": 0})
            continue

        sims = _sim_matrix(all_minority, majority_list) if majority_list else [0.0] * len(all_minority)

        rec = {
            "paper_id": pid,
            "union": len(union),
            "majority": len(majority),
            "minority": len(all_minority),
            "minority_sims": [round(s, 3) for s in sims],
        }
        for th in THRESHOLDS:
            kept = sum(1 for s in sims if s >= th)
            rec[f"mary_kept@{th}"] = kept
            rec[f"mary_pruned@{th}"] = len(all_minority) - kept
        results.append(rec)

        print(f"  {pid}: union={len(union)} maj={len(majority)} min={len(all_minority)} "
              f"sims[min={min(sims):.2f},med={sorted(sims)[len(sims)//2]:.2f},max={max(sims):.2f}] "
              f"kept@0.5={rec['mary_kept@0.5']} pruned@0.5={rec['mary_pruned@0.5']}", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # aggregate
    print("\n=== MARY FUSION SUMMARY ===")
    tot_union = sum(r["union"] for r in results)
    tot_maj = sum(r["majority"] for r in results)
    tot_min = sum(r["minority"] for r in results)
    print(f"total union: {tot_union} | majority(both): {tot_maj} | minority(one): {tot_min}")
    for th in THRESHOLDS:
        kept = sum(r.get(f"mary_kept@{th}", 0) for r in results)
        pruned = sum(r.get(f"mary_pruned@{th}", 0) for r in results)
        print(f"  MARY@{th}: kept {kept}/{tot_min} minority, pruned {pruned} ({pruned/max(tot_min,1)*100:.0f}% of minority)")
    print(f"\nraw union would keep ALL {tot_min} minority atoms (noise risk)")
    print(f"majority vote would keep ONLY {tot_maj} (loses valid minority)")
    print(f"MARY@0.5 keeps {sum(r.get('mary_kept@0.5',0) for r in results)} — between the two")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
