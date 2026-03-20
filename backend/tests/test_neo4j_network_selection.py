from app.graph.neo4j_client import _select_network_base_nodes


def test_select_network_base_nodes_prefers_connected_backbone_over_newer_isolates() -> None:
    base_nodes = [
        {"id": "new-1", "year": 2026},
        {"id": "new-2", "year": 2025},
        {"id": "hub", "year": 2022},
        {"id": "bridge", "year": 2021},
        {"id": "peer", "year": 2020},
        {"id": "leaf", "year": 2019},
    ]
    candidate_edges = [
        {"source": "hub", "target": "bridge", "total_mentions": 8},
        {"source": "hub", "target": "peer", "total_mentions": 6},
        {"source": "bridge", "target": "peer", "total_mentions": 5},
    ]

    selected = _select_network_base_nodes(base_nodes, candidate_edges, limit_papers=3)

    assert [node["id"] for node in selected] == ["hub", "bridge", "peer"]


def test_select_network_base_nodes_falls_back_to_recency_when_graph_has_no_edges() -> None:
    base_nodes = [
        {"id": "paper-1", "year": 2026},
        {"id": "paper-2", "year": 2025},
        {"id": "paper-3", "year": 2024},
    ]

    selected = _select_network_base_nodes(base_nodes, [], limit_papers=2)

    assert [node["id"] for node in selected] == ["paper-1", "paper-2"]
