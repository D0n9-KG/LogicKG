from types import SimpleNamespace

import pytest

from app.evolution.service import (
    _compute_evolution_quality_metrics,
    _enforce_evolution_quality_gates,
)


def test_compute_coverage_rate():
    """Test coverage calculation"""
    inferred_events = [
        {"source_prop_id": "A", "target_prop_id": "B", "status": "accepted", "event_type": "SUPPORTS"},
        {"source_prop_id": "B", "target_prop_id": "C", "status": "accepted", "event_type": "SUPPORTS"},
        {"source_prop_id": "D", "target_prop_id": "E", "status": "pending_review", "event_type": "SUPPORTS"},
    ]

    supports = [
        {"source_prop_id": "A", "target_prop_id": "B"},
        {"source_prop_id": "B", "target_prop_id": "C"},
    ]

    total_propositions = 10

    metrics = _compute_evolution_quality_metrics(
        inferred_events=inferred_events,
        supports=supports,
        challenges=[],
        supersedes=[],
        total_propositions=total_propositions
    )

    # Covered propositions: A, B, C (3 unique)
    # Coverage: 3/10 = 0.30
    assert metrics["coverage_rate"] == 0.30
    assert metrics["covered_propositions"] == 3
    assert metrics["total_propositions"] == 10


def test_compute_self_loop_rate():
    """Test self-loop rate calculation"""
    inferred_events = [
        {"source_prop_id": "A", "target_prop_id": "B", "status": "accepted", "event_type": "SUPPORTS"},
        {"source_prop_id": "B", "target_prop_id": "B", "status": "accepted", "event_type": "SUPPORTS"},  # Self-loop
        {"source_prop_id": "C", "target_prop_id": "D", "status": "accepted", "event_type": "SUPPORTS"},
    ]

    metrics = _compute_evolution_quality_metrics(
        inferred_events=inferred_events,
        supports=[],
        challenges=[],
        supersedes=[],
        total_propositions=10
    )

    # Total accepted: 3, self-loops: 1
    # Self-loop rate: 1/3 = 0.333...
    assert abs(metrics["self_loop_rate"] - 0.333) < 0.01
    assert metrics["self_loop_count"] == 1
    assert metrics["total_accepted_events"] == 3


def test_mention_origin_excluded_from_self_loops():
    """Test that mention-origin events are excluded from self-loop counting"""
    inferred_events = [
        {"source_prop_id": "A", "target_prop_id": "A", "status": "accepted", "origin": "mention"},  # Mention self-loop (excluded)
        {"source_prop_id": "B", "target_prop_id": "B", "status": "accepted", "origin": "inferred"},  # Inferred self-loop (counted)
        {"source_prop_id": "C", "target_prop_id": "D", "status": "accepted"},  # Normal event (no origin field)
    ]

    metrics = _compute_evolution_quality_metrics(
        inferred_events=inferred_events,
        supports=[],
        challenges=[],
        supersedes=[],
        total_propositions=10
    )

    # Only events without origin="mention" count: 2 accepted (B->B self-loop, C->D normal)
    # Self-loops: 1 (B->B)
    assert metrics["self_loop_count"] == 1
    assert metrics["total_accepted_events"] == 2
    assert metrics["self_loop_rate"] == 0.5


def test_zero_denominators():
    """Test behavior with zero denominators"""
    metrics = _compute_evolution_quality_metrics(
        inferred_events=[],
        supports=[],
        challenges=[],
        supersedes=[],
        total_propositions=0
    )

    assert metrics["coverage_rate"] == 0.0
    assert metrics["self_loop_rate"] == 0.0
    assert metrics["covered_propositions"] == 0
    assert metrics["self_loop_count"] == 0
    assert metrics["total_accepted_events"] == 0


def test_gate_fails_on_low_coverage():
    """Gate should fail when coverage is below threshold."""
    metrics = {
        "coverage_rate": 0.15,  # 15% < 20%
        "covered_propositions": 15,
        "total_propositions": 100,
        "self_loop_rate": 0.02,
        "self_loop_count": 2,
        "total_accepted_events": 100,
    }
    gate_settings = SimpleNamespace(
        evolution_gate_enabled=True,
        evolution_min_coverage=0.20,
        evolution_max_self_loop_rate=0.05,
    )

    with pytest.raises(ValueError) as exc_info:
        _enforce_evolution_quality_gates(metrics, gate_settings)

    message = str(exc_info.value)
    assert "coverage rate" in message.lower()
    assert "15.00%" in message
    assert "20.00%" in message
    assert "15/100" in message


def test_gate_fails_on_high_self_loops():
    """Gate should fail when self-loop rate exceeds threshold."""
    metrics = {
        "coverage_rate": 0.25,
        "covered_propositions": 25,
        "total_propositions": 100,
        "self_loop_rate": 0.08,  # 8% > 5%
        "self_loop_count": 8,
        "total_accepted_events": 100,
    }
    gate_settings = SimpleNamespace(
        evolution_gate_enabled=True,
        evolution_min_coverage=0.20,
        evolution_max_self_loop_rate=0.05,
    )

    with pytest.raises(ValueError) as exc_info:
        _enforce_evolution_quality_gates(metrics, gate_settings)

    message = str(exc_info.value)
    assert "self-loop rate" in message.lower()
    assert "8.00%" in message
    assert "5.00%" in message
    assert "8/100" in message


def test_gate_passes_with_good_metrics():
    """Gate should pass when all quality metrics are within thresholds."""
    metrics = {
        "coverage_rate": 0.25,  # 25% >= 20%
        "covered_propositions": 25,
        "total_propositions": 100,
        "self_loop_rate": 0.02,  # 2% <= 5%
        "self_loop_count": 2,
        "total_accepted_events": 100,
    }
    gate_settings = SimpleNamespace(
        evolution_gate_enabled=True,
        evolution_min_coverage=0.20,
        evolution_max_self_loop_rate=0.05,
    )

    _enforce_evolution_quality_gates(metrics, gate_settings)


def test_gate_disabled_allows_all_metrics():
    """Gate should skip validation when explicitly disabled."""
    metrics = {
        "coverage_rate": 0.05,  # Bad, but should be ignored
        "self_loop_rate": 0.50,  # Bad, but should be ignored
    }
    gate_settings = SimpleNamespace(evolution_gate_enabled=False)

    _enforce_evolution_quality_gates(metrics, gate_settings)


def test_gate_passes_on_exact_boundaries():
    """Gate should pass when metrics exactly equal thresholds."""
    metrics = {
        "coverage_rate": 0.20,  # Exactly 20%
        "covered_propositions": 20,
        "total_propositions": 100,
        "self_loop_rate": 0.05,  # Exactly 5%
        "self_loop_count": 5,
        "total_accepted_events": 100,
    }
    gate_settings = SimpleNamespace(
        evolution_gate_enabled=True,
        evolution_min_coverage=0.20,
        evolution_max_self_loop_rate=0.05,
    )

    # Should pass at boundary
    _enforce_evolution_quality_gates(metrics, gate_settings)
