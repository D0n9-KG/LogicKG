from __future__ import annotations

from app.community.remote_graph_normalizer import normalize_remote_graph_payload


def test_normalize_remote_graph_payload_drops_remote_community_keyword_and_super_nodes() -> None:
    payload = {
        "nodes": [
            {"id": "entity-1", "label": "entity", "properties": {"name": "Bubble"}},
            {"id": "entity-2", "label": "entity", "properties": {"name": "Collapse"}},
            {"id": "community-1", "label": "community", "properties": {"name": "Chapter cluster"}},
            {"id": "keyword-1", "label": "keyword", "properties": {"name": "stability"}},
            {"id": "super-1", "label": "super-node", "properties": {"name": "Chapter super node"}},
        ],
        "edges": [
            {"start_id": "entity-1", "end_id": "entity-2", "relation": "related_to"},
            {"start_id": "entity-1", "end_id": "community-1", "relation": "member_of"},
            {"start_id": "keyword-1", "end_id": "community-1", "relation": "keyword_of"},
            {"start_id": "entity-2", "end_id": "super-1", "relation": "belongs_to"},
        ],
        "communities": [{"id": 7, "members": ["entity-1", "entity-2"]}],
    }

    normalized = normalize_remote_graph_payload(payload)

    assert [node["id"] for node in normalized["nodes"]] == ["entity-1", "entity-2"]
    assert normalized["edges"] == [
        {"start_id": "entity-1", "end_id": "entity-2", "relation": "related_to"}
    ]
    assert normalized["communities"] == []
