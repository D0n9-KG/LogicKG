from __future__ import annotations


def _status_order(status: str) -> int:
    s = str(status or "").strip().lower()
    if s == "accepted":
        return 4
    if s == "ranked":
        return 3
    if s == "needs_more_evidence":
        return 2
    if s == "draft":
        return 1
    if s == "rejected":
        return 0
    return 1


def rank_candidates(candidates: list[dict]) -> list[dict]:
    """Rank candidates by status + quality + scientific utility signals."""
    ordered = sorted(
        [dict(c) for c in (candidates or [])],
        key=lambda c: (
            _status_order(str(c.get("status") or "")),
            float(c.get("quality_score") or 0.0),
            float(c.get("optimization_score") or 0.0),
            float(c.get("support_coverage") or 0.0),
            float(c.get("novelty_score") or 0.0),
            float(c.get("relevance_score") or 0.0),
            str(c.get("candidate_id") or ""),
        ),
        reverse=True,
    )
    for idx, row in enumerate(ordered, start=1):
        row["rank"] = idx
    return ordered
