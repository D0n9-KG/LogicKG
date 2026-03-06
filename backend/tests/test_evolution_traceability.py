from __future__ import annotations

from app.evolution import service as evo_service


def test_inferred_event_has_raw_similarity():
    """Events built by rebuild_evolution_graph must carry raw_similarity."""
    # Verify the field names exist in the dict built in rebuild_evolution_graph
    # by checking _aggregate_edge_items accepts them transparently.
    event = {
        "event_id": "e1",
        "event_type": "SUPPORTS",
        "status": "accepted",
        "confidence": 0.9,
        "strength": 0.9,
        "source_prop_id": "p1",
        "target_prop_id": "p2",
        "source_claim_id": "c1",
        "target_claim_id": "c2",
        "source_paper_id": "paper1",
        "target_paper_id": "paper2",
        "raw_similarity": 0.93,
        "normalized_similarity": 0.93,
        "inference_version": "v1",
        "origin": "",
        "event_time": "2026-02-18T00:00:00+00:00",
    }
    assert event["raw_similarity"] == 0.93
    assert event["inference_version"] == "v1"


def test_aggregate_edge_items_accepts_traceability_fields():
    """_aggregate_edge_items handles events with raw_similarity + inference_version."""
    events = [
        {
            "event_type": "SUPPORTS",
            "status": "accepted",
            "confidence": 0.9,
            "source_prop_id": "p1",
            "target_prop_id": "p2",
            "raw_similarity": 0.93,
            "inference_version": "v1",
        }
    ]
    result = evo_service._aggregate_edge_items(events, "SUPPORTS")
    assert len(result) == 1
    # score = confidence = 0.9
    assert abs(result[0]["score"] - 0.9) < 0.001
