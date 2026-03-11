from __future__ import annotations

from typing import Any


def _clamp01(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return float(value)


def _avg_metric(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    values: list[float] = []
    for row in rows:
        try:
            values.append(_clamp01(float((row or {}).get(key) or 0.0)))
        except Exception:
            values.append(0.0)
    return sum(values) / max(len(values), 1)


def compute_discovery_metrics(rows: list[dict[str, Any]] | None) -> dict[str, float]:
    items = [dict(row or {}) for row in (rows or [])]
    support = _avg_metric(items, "support_coverage")
    challenge = _avg_metric(items, "challenge_coverage")
    benchmark = _avg_metric(items, "benchmark_coverage")
    novelty = _avg_metric(items, "novelty_score")
    quality = _avg_metric(items, "quality_score")
    return {
        "support_coverage": support,
        "challenge_coverage": challenge,
        "benchmark_coverage": benchmark,
        "novelty_score": novelty,
        "quality_score": quality,
        "overall_score": (support + challenge + benchmark + novelty + quality) / 5.0,
        "count": float(len(items)),
    }
