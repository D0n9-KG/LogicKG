from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any


_TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "method",
    "result",
    "theory",
}


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN_RE.findall(str(text or "").lower()):
        if len(tok) <= 1:
            continue
        if tok in _STOPWORDS:
            continue
        out.append(tok)
    return out


def extract_fusion_keywords(
    communities: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    node_map = {str(n.get("id") or "").strip(): n for n in nodes if str(n.get("id") or "").strip()}
    rows: list[dict[str, Any]] = []

    for community in communities:
        cid = str(community.get("community_id") or "").strip()
        if not cid:
            continue
        member_ids = [str(x).strip() for x in (community.get("member_ids") or []) if str(x).strip()]
        corpus = []
        for mid in member_ids:
            node = node_map.get(mid)
            if not node:
                continue
            corpus.append(str(node.get("text") or ""))
            corpus.append(str(node.get("evidence_quote") or ""))
        counts = Counter(_tokens(" ".join(corpus)))
        ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[: max(1, int(top_k))]

        for idx, (kw, freq) in enumerate(ranked):
            seed = f"{cid}\0{kw}"
            kid = "fk:" + hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:12]
            rows.append(
                {
                    "community_id": cid,
                    "keyword_id": kid,
                    "keyword": kw,
                    "rank": idx + 1,
                    "weight": float(freq),
                }
            )

    rows.sort(key=lambda r: (str(r["community_id"]), int(r["rank"]), str(r["keyword"])))
    return rows
