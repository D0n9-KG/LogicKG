from __future__ import annotations

from typing import Any


def _rrf_fuse(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    k_rrf: int = 60,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion across multiple ranked result lists."""
    scores: dict[str, float] = {}
    first_seen: dict[str, dict[str, Any]] = {}
    for ranked in ranked_lists:
        seen_in_ranked: set[str] = set()
        for rank, item in enumerate(ranked, start=1):
            if not isinstance(item, dict):
                continue
            raw_chunk_id = item.get("chunk_id")
            chunk_id = str(raw_chunk_id).strip() if raw_chunk_id is not None else ""
            if not chunk_id or chunk_id.lower() == "none" or chunk_id in seen_in_ranked:
                continue
            seen_in_ranked.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k_rrf + rank)
            if chunk_id not in first_seen:
                normalized = dict(item)
                normalized["chunk_id"] = chunk_id
                first_seen[chunk_id] = normalized

    fused: list[dict[str, Any]] = []
    for chunk_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        entry = dict(first_seen[chunk_id])
        entry["rrf_score"] = score
        fused.append(entry)
    return fused


def merge_evidence(
    *,
    faiss: list[dict[str, Any]],
    lexical: list[dict[str, Any]],
    k: int,
) -> list[dict[str, Any]]:
    """Merge FAISS and lexical retrieval outputs with RRF, fallback-safe."""
    want = max(1, int(k))
    if lexical:
        return _rrf_fuse([faiss, lexical])[:want]
    return list(faiss[:want])
