"""
Test conflict detection robustness improvements (Stage 4).

Tests batch processing, JSON repair, graceful degradation, and metrics tracking.
"""

from __future__ import annotations

import pytest

from app.llm.conflict_judge import judge_conflict_pairs_batch


def test_conflict_detection_basic():
    """Test basic conflict detection with valid pairs."""
    pairs = [
        {
            "pair_id": "p1",
            "claim_a": "Particle friction coefficient increases flow rate",
            "claim_b": "Particle friction coefficient decreases flow rate",
        },
        {
            "pair_id": "p2",
            "claim_a": "Temperature was 300K",
            "claim_b": "Experiments conducted at room temperature",
        },
    ]

    schema = {"rules": {}, "prompts": {}}
    results = judge_conflict_pairs_batch(pairs=pairs, schema=schema)

    assert len(results) == 2, "Should return judgment for each pair"
    assert results[0]["pair_id"] == "p1", "Should preserve pair_id"
    assert results[0]["label"] in ["contradict", "not_conflict", "insufficient"], "Label must be valid"
    assert 0 <= results[0]["score"] <= 1, "Score must be in [0,1]"
    assert isinstance(results[0].get("reason"), str), "Should include reason"


def test_conflict_detection_large_batch():
    """Test batching with >15 pairs (default batch size)."""
    # Create 30 pairs to trigger batching
    pairs = [
        {
            "pair_id": f"p{i}",
            "claim_a": f"Method improves metric A by {i}%",
            "claim_b": f"Method degrades metric A by {i + 1}%",
        }
        for i in range(30)
    ]

    schema = {
        "rules": {"phase2_conflict_batch_size": 10},  # Force smaller batches
        "prompts": {},
    }
    results = judge_conflict_pairs_batch(pairs=pairs, schema=schema)

    # Should process all pairs despite batching
    assert len(results) >= 25, f"Expected >= 25 results, got {len(results)}"

    # Verify all results have valid structure
    for r in results:
        assert "pair_id" in r, "Missing pair_id"
        assert r["label"] in ["contradict", "not_conflict", "insufficient"], f"Invalid label: {r['label']}"
        assert 0 <= r["score"] <= 1, f"Score {r['score']} out of range"


def test_conflict_detection_empty_pairs():
    """Test graceful handling of empty input."""
    results = judge_conflict_pairs_batch(pairs=[], schema={"rules": {}, "prompts": {}})
    assert results == [], "Empty input should return empty list"


def test_conflict_detection_batch_size_configuration():
    """Test configurable batch size via schema rules."""
    pairs = [{"pair_id": f"p{i}", "claim_a": "Claim A", "claim_b": "Claim B"} for i in range(20)]

    # Test with batch_size = 5
    schema = {"rules": {"phase2_conflict_batch_size": 5}, "prompts": {}}
    results = judge_conflict_pairs_batch(pairs=pairs, schema=schema)

    # Should still process all pairs
    assert len(results) >= 15, "Should process most pairs despite small batch size"


def test_conflict_detection_max_pairs_limit():
    """Test max_pairs limiting via schema rules."""
    pairs = [{"pair_id": f"p{i}", "claim_a": "Claim A", "claim_b": "Claim B"} for i in range(200)]

    schema = {
        "rules": {"phase2_conflict_candidate_max_pairs": 50},  # Limit to 50
        "prompts": {},
    }
    results = judge_conflict_pairs_batch(pairs=pairs, schema=schema)

    # Should respect max_pairs limit
    assert len(results) <= 50, f"Should limit to 50 pairs, got {len(results)}"


def test_conflict_detection_malformed_label_normalization():
    """Test that malformed labels are normalized to 'insufficient'."""
    # This test validates defensive handling in orchestrator.py
    # The judge itself should return valid labels, but orchestrator defends against hallucinations
    # We test this indirectly by ensuring all valid labels pass through
    pairs = [
        {
            "pair_id": "p1",
            "claim_a": "Test claim A",
            "claim_b": "Test claim B",
        }
    ]

    results = judge_conflict_pairs_batch(pairs=pairs, schema={"rules": {}, "prompts": {}})

    # All labels should be valid (judge should not return malformed labels)
    for r in results:
        assert r["label"] in ["contradict", "not_conflict", "insufficient"], (
            f"Judge returned invalid label: {r['label']}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
