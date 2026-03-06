from app.ingest.textbook_proposition_mapper import map_entities_to_propositions


def test_only_assertive_entity_types_are_mapped():
    items = [
        {"entity_id": "e1", "entity_type": "theory", "name": "A"},
        {"entity_id": "e2", "entity_type": "concept", "name": "B"},
    ]
    out = map_entities_to_propositions(items)
    assert len(out) == 1
    assert out[0]["entity_id"] == "e1"
