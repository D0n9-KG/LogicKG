from app.graph.textbook_graph import build_community_rows


def test_build_community_rows_prefers_explicit_youtu_membership() -> None:
    entities = [
        {"entity_id": "e-1", "name": "Bubble", "attributes": '{"community_id": 7}'},
        {"entity_id": "e-2", "name": "Collapse", "attributes": '{"community_id": 7}'},
        {"entity_id": "e-3", "name": "Pressure", "attributes": '{"community_id": 9}'},
    ]
    relations = [
        {"source_id": "e-1", "target_id": "e-2", "rel_type": "causes"},
        {"source_id": "e-2", "target_id": "e-3", "rel_type": "changes"},
    ]

    communities = build_community_rows(entities, relations)

    assert len(communities) == 2
    by_id = {row["community_id"]: row for row in communities}
    assert set(by_id["community:7"]["member_ids"]) == {"e-1", "e-2"}
    assert by_id["community:7"]["source"] == "youtu"
    assert set(by_id["community:9"]["member_ids"]) == {"e-3"}


def test_build_community_rows_derives_clusters_when_membership_missing() -> None:
    entities = [
        {"entity_id": "e-1", "name": "Bubble", "attributes": "{}"},
        {"entity_id": "e-2", "name": "Collapse", "attributes": "{}"},
        {"entity_id": "e-3", "name": "Pressure", "attributes": "{}"},
        {"entity_id": "e-4", "name": "Velocity", "attributes": "{}"},
    ]
    relations = [
        {"source_id": "e-1", "target_id": "e-2", "rel_type": "causes"},
        {"source_id": "e-3", "target_id": "e-4", "rel_type": "changes"},
    ]

    communities = build_community_rows(entities, relations)

    assert len(communities) == 2
    sizes = sorted(row["size"] for row in communities)
    assert sizes == [2, 2]
    assert {row["source"] for row in communities} == {"derived"}
