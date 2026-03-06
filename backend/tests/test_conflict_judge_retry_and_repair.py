"""Tests for conflict judge retry and repair improvements (Blocker 4.1 & 4.2)."""
from __future__ import annotations

from unittest.mock import patch

from app.llm.conflict_judge import judge_conflict_pairs_batch


def _pair(pid: str) -> dict[str, str]:
    """Create a test conflict pair."""
    return {
        "pair_id": pid,
        "claim_a": f"Claim A {pid}",
        "claim_b": f"Claim B {pid}",
    }


def test_conflict_judge_repairs_malformed_json_response() -> None:
    """Test that JSON repair is effectively used for malformed responses."""
    # Malformed JSON with trailing commas (common LLM error)
    malformed = '{"items":[{"pair_id":"p1","label":"contradict","score":0.91,"reason":"direct negation",}],}'

    with patch("app.llm.client.call_text", return_value=malformed):
        rows = judge_conflict_pairs_batch(
            pairs=[_pair("p1")],
            schema={"rules": {}, "prompts": {}},
        )

    assert len(rows) == 1
    assert rows[0]["pair_id"] == "p1"
    assert rows[0]["label"] == "contradict"
    assert rows[0]["score"] == 0.91


def test_conflict_judge_marks_batch_insufficient_when_unrepairable() -> None:
    """Test graceful degradation when JSON is completely unrepairable."""
    with patch("app.llm.client.call_text", return_value="not a json response at all"):
        rows = judge_conflict_pairs_batch(
            pairs=[_pair("p1")],
            schema={"rules": {}, "prompts": {}},
        )

    assert len(rows) == 1
    assert rows[0]["pair_id"] == "p1"
    assert rows[0]["label"] == "insufficient"


def test_conflict_judge_avoids_outer_retry_amplification() -> None:
    """
    Test that retry amplification is avoided.

    With the fix, there's NO outer retry loop in conflict_judge.
    Retry happens only at client layer (call_text with retry=True).
    This test verifies that batch failures result in exactly N calls for N batches.
    """
    pairs = [_pair(f"p{i}") for i in range(16)]
    schema = {
        "rules": {"phase2_conflict_batch_size": 8},
        "prompts": {},
    }

    with patch("app.llm.client.call_text", side_effect=RuntimeError("upstream failure")) as mocked_call:
        rows = judge_conflict_pairs_batch(
            pairs=pairs,
            schema=schema,
        )

    # 16 pairs / 8 batch_size = 2 batches => exactly 2 calls
    # Old code would retry each batch 3 times = 6 calls
    assert mocked_call.call_count == 2
    assert len(rows) == 16
    assert all(r["label"] == "insufficient" for r in rows)


def test_conflict_judge_extracts_json_from_markdown_code_blocks() -> None:
    """Test that JSON wrapped in markdown code blocks is properly extracted."""
    markdown_response = """Here's the analysis:

```json
{"items":[{"pair_id":"p1","label":"not_conflict","score":0.2,"reason":"compatible"}]}
```

That's my assessment."""

    with patch("app.llm.client.call_text", return_value=markdown_response):
        rows = judge_conflict_pairs_batch(
            pairs=[_pair("p1")],
            schema={"rules": {}, "prompts": {}},
        )

    assert len(rows) == 1
    assert rows[0]["pair_id"] == "p1"
    assert rows[0]["label"] == "not_conflict"
    assert rows[0]["score"] == 0.2


def test_conflict_judge_extracts_json_from_text_with_extra_content() -> None:
    """Test that JSON is extracted even when surrounded by extra text."""
    messy_response = """Let me analyze these pairs carefully.

Based on my analysis: {"items":[{"pair_id":"p1","label":"contradict","score":0.85,"reason":"opposite claims"}]}

This concludes my judgment."""

    with patch("app.llm.client.call_text", return_value=messy_response):
        rows = judge_conflict_pairs_batch(
            pairs=[_pair("p1")],
            schema={"rules": {}, "prompts": {}},
        )

    assert len(rows) == 1
    assert rows[0]["pair_id"] == "p1"
    assert rows[0]["label"] == "contradict"
    assert rows[0]["score"] == 0.85


def test_conflict_judge_normalizes_invalid_labels() -> None:
    """Test that invalid labels are normalized to 'insufficient'."""
    response_with_invalid_label = '{"items":[{"pair_id":"p1","label":"maybe_conflict","score":0.5,"reason":"unclear"}]}'

    with patch("app.llm.client.call_text", return_value=response_with_invalid_label):
        rows = judge_conflict_pairs_batch(
            pairs=[_pair("p1")],
            schema={"rules": {}, "prompts": {}},
        )

    assert len(rows) == 1
    assert rows[0]["pair_id"] == "p1"
    assert rows[0]["label"] == "insufficient"  # Normalized from "maybe_conflict"


def test_conflict_judge_clamps_scores_to_valid_range() -> None:
    """Test that scores outside [0,1] are clamped."""
    response_with_invalid_scores = '{"items":[{"pair_id":"p1","label":"contradict","score":1.5,"reason":"test"},{"pair_id":"p2","label":"not_conflict","score":-0.3,"reason":"test"}]}'

    with patch("app.llm.client.call_text", return_value=response_with_invalid_scores):
        rows = judge_conflict_pairs_batch(
            pairs=[_pair("p1"), _pair("p2")],
            schema={"rules": {}, "prompts": {}},
        )

    assert len(rows) == 2
    assert rows[0]["score"] == 1.0  # Clamped from 1.5
    assert rows[1]["score"] == 0.0  # Clamped from -0.3


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
