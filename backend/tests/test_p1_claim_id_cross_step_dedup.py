# backend/tests/test_p1_claim_id_cross_step_dedup.py
"""
Tests for P1 Fix: cross-step claim_id collision resolution in _merge_claim_candidates.

Root cause: bucket_key = hash(step_type + text), but claim_id = hash(text) only.
Same text in different steps → same claim_id but different step_type → DB corruption.
Fix: after sort-by-priority, deduplicate by claim_id keeping first (highest priority).
"""
from __future__ import annotations

from app.extraction.orchestrator import _merge_claim_candidates


def _make_claim(text: str, step_type: str, confidence: float = 0.8, chunk_id: str = "c1") -> dict:
    return {
        "text": text,
        "step_type": step_type,
        "confidence": confidence,
        "origin_chunk_id": chunk_id,
        "worker_id": "w1",
        "kinds": ["Result"],
    }


def test_no_collision_returns_all_claims():
    """When each step has unique text, all claims survive."""
    claims = [
        _make_claim("Background claim", "Background"),
        _make_claim("Method claim", "Method"),
    ]
    result = _merge_claim_candidates(
        claims=claims,
        paper_id="doi:10.1000/test",
        doi="10.1000/test",
        step_order=["Background", "Method"],
    )
    assert len(result) == 2
    step_types = {r["step_type"] for r in result}
    assert step_types == {"Background", "Method"}


def test_cross_step_duplicate_text_keeps_higher_priority_step():
    """Same text in Background (rank 0) and Method (rank 1): Background wins."""
    same_text = "The model improves performance significantly"
    claims = [
        _make_claim(same_text, "Background", confidence=0.7),
        _make_claim(same_text, "Method", confidence=0.9),  # Higher confidence, but lower step priority
    ]
    result = _merge_claim_candidates(
        claims=claims,
        paper_id="doi:10.1000/test",
        doi="10.1000/test",
        step_order=["Background", "Method"],
    )
    # Only one claim should survive (Background has higher priority: rank 0 < rank 1)
    assert len(result) == 1
    assert result[0]["step_type"] == "Background"


def test_cross_step_duplicate_text_dedup_by_claim_id():
    """Duplicate same text across 3 steps: only the first-priority step survives."""
    same_text = "Results demonstrate significant improvement over baseline methods"
    claims = [
        _make_claim(same_text, "Result", confidence=0.9),
        _make_claim(same_text, "Conclusion", confidence=0.85),
        _make_claim(same_text, "Method", confidence=0.95),  # Highest conf but lowest priority
    ]
    step_order = ["Background", "Method", "Result", "Conclusion"]
    result = _merge_claim_candidates(
        claims=claims,
        paper_id="doi:10.1000/test",
        doi="10.1000/test",
        step_order=step_order,
    )
    # Only one claim survives: Method has rank 1, Result rank 2, Conclusion rank 3
    assert len(result) == 1
    assert result[0]["step_type"] == "Method"


def test_within_step_dedup_still_works():
    """Same text in the same step is merged into one claim (existing behavior)."""
    same_text = "The algorithm is efficient"
    claims = [
        _make_claim(same_text, "Method", confidence=0.8, chunk_id="c1"),
        _make_claim(same_text, "Method", confidence=0.6, chunk_id="c2"),  # Same step, same text
    ]
    result = _merge_claim_candidates(
        claims=claims,
        paper_id="doi:10.1000/test",
        doi="10.1000/test",
        step_order=["Method"],
    )
    # Within-step, same text → merged to 1 bucket → 1 claim
    assert len(result) == 1
    assert result[0]["step_type"] == "Method"


def test_mixed_unique_and_duplicate_preserves_unique():
    """Mix of unique and duplicate texts: unique claims all survive, only first duplicate kept."""
    claims = [
        _make_claim("Unique background", "Background"),
        _make_claim("Shared claim text", "Background"),
        _make_claim("Unique method", "Method"),
        _make_claim("Shared claim text", "Method"),  # Cross-step duplicate
    ]
    result = _merge_claim_candidates(
        claims=claims,
        paper_id="doi:10.1000/test",
        doi="10.1000/test",
        step_order=["Background", "Method"],
    )
    # 3 unique claim_ids: "Unique background", "Shared claim text" (Background wins), "Unique method"
    assert len(result) == 3
    texts = {r["text"] for r in result}
    assert "Unique background" in texts
    assert "Unique method" in texts

    # "Shared claim text" should be from Background (higher priority)
    shared = [r for r in result if "Shared" in r["text"]]
    assert len(shared) == 1
    assert shared[0]["step_type"] == "Background"


def test_collision_merges_origin_chunk_ids_from_duplicate():
    """Evidence from lower-priority duplicate is merged into kept item."""
    same_text = "The proposed method outperforms all baselines"
    claims = [
        _make_claim(same_text, "Background", confidence=0.7, chunk_id="chunk-bg"),
        _make_claim(same_text, "Result", confidence=0.9, chunk_id="chunk-result"),
    ]
    result = _merge_claim_candidates(
        claims=claims,
        paper_id="doi:10.1000/test",
        doi="10.1000/test",
        step_order=["Background", "Method", "Result"],
    )
    # Only one claim, from Background (higher priority)
    assert len(result) == 1
    assert result[0]["step_type"] == "Background"

    # BUT the origin_chunk_ids should include both chunks (merged evidence)
    chunk_ids = result[0].get("origin_chunk_ids") or []
    assert "chunk-bg" in chunk_ids
    assert "chunk-result" in chunk_ids


def test_collision_logs_warning(caplog):
    """Warning is emitted when cross-step claim_id collision is detected."""
    import logging

    same_text = "Cross step collision trigger text"
    claims = [
        _make_claim(same_text, "Background"),
        _make_claim(same_text, "Method"),
    ]
    with caplog.at_level(logging.WARNING, logger="app.extraction.orchestrator"):
        result = _merge_claim_candidates(
            claims=claims,
            paper_id="doi:10.1000/test",
            doi="10.1000/test",
            step_order=["Background", "Method"],
        )

    assert len(result) == 1
    # Verify warning was logged with the discarded step_type
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("cross-step claim_id collision" in msg for msg in warning_messages)
    assert any("Method" in msg for msg in warning_messages)  # Method is discarded
