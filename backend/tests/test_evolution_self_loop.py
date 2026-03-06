from __future__ import annotations

from app.evolution.inference import infer_relation_type, normalize_proposition_text


def test_identical_text_returns_merge_not_supports():
    """Test that identical normalized text triggers MERGE instead of SUPPORTS"""
    source_text = "Granular flow increases with vibration."
    target_text = "Granular flow increases with vibration."  # Exact duplicate

    result = infer_relation_type(
        source_text=source_text,
        target_text=target_text,
        similarity=0.98,
        target_confidence=0.9,
        min_similarity=0.85,
        accepted_threshold=0.82,
    )

    assert result is not None
    assert result["event_type"] == "MERGE"
    assert result["status"] == "accepted"
    assert result.get("reason") == "text_identity"
    assert result["confidence"] >= 0.95


def test_identical_normalized_text_returns_merge():
    """Test that text identity is detected after normalization"""
    source_text = "  Granular Flow Increases WITH vibration.  "
    target_text = "granular flow increases with vibration"  # Different case/whitespace

    assert normalize_proposition_text(source_text) == normalize_proposition_text(target_text)

    result = infer_relation_type(
        source_text=source_text,
        target_text=target_text,
        similarity=0.95,
        target_confidence=0.8,
        min_similarity=0.85,
        accepted_threshold=0.82,
    )

    assert result is not None
    assert result["event_type"] == "MERGE"


def test_similar_but_different_text_returns_relation():
    """Test that similar (but not identical) text still generates relations"""
    source_text = "Granular flow increases with vibration."
    target_text = "These results support the finding that vibration increases granular flow rate."  # Similar + support marker

    result = infer_relation_type(
        source_text=source_text,
        target_text=target_text,
        similarity=0.92,
        target_confidence=0.85,
        min_similarity=0.85,
        accepted_threshold=0.82,
    )

    assert result is not None
    # Should return a relation type (SUPPORTS, CHALLENGES, or SUPERSEDES), not MERGE
    assert result["event_type"] in ["SUPPORTS", "CHALLENGES", "SUPERSEDES"]
    assert result["event_type"] != "MERGE"


def test_merge_events_skipped_in_evolution_service():
    """Test that MERGE events are not added to inferred_events (integration-like test)"""
    # This is more of a documentation test showing the expected behavior
    # In rebuild_evolution_graph, when infer_relation_type returns MERGE:
    # 1. Event is logged
    # 2. Event is NOT added to inferred_events
    # 3. No SUPPORTS edge is created for this pair

    # Simulating the service logic:
    inferred = infer_relation_type(
        source_text="Same text",
        target_text="Same text",
        similarity=0.99,
        target_confidence=0.9,
        min_similarity=0.85,
        accepted_threshold=0.82,
    )

    assert inferred["event_type"] == "MERGE"

    # In service code, this would trigger `continue`, skipping the event
    # So no SUPPORTS edge would be created
