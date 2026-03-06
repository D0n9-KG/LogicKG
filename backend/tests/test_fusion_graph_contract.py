import json
from pathlib import Path

import app.fusion.service as fusion_service


class _FakeNeo4jClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def list_fusion_graph(self, limit_nodes: int = 1000, limit_edges: int = 3000):
        return {
            "nodes": [
                {"id": "n1", "label": "LogicStep", "text": "step one"},
                {"id": "n2", "label": "KnowledgeEntity", "text": "entity"},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "type": "EXPLAINS", "weight": 0.9},
                {"source": "ghost", "target": "n2", "type": "EXPLAINS", "weight": 0.8},
                {"source": "n1", "target": "missing", "type": "EXPLAINS", "weight": 0.7},
            ],
        }


def test_get_fusion_graph_filters_edges_outside_node_set_on_neo4j_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fusion_service, "_snapshot_file", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(fusion_service, "Neo4jClient", _FakeNeo4jClient)

    out = fusion_service.get_fusion_graph(limit_nodes=10, limit_edges=10)

    assert out["source"] == "neo4j"
    assert len(out["nodes"]) == 2
    assert len(out["edges"]) == 1
    assert out["edges"][0]["source"] == "n1"
    assert out["edges"][0]["target"] == "n2"


def test_get_fusion_graph_filters_edges_outside_node_set_on_snapshot(monkeypatch, tmp_path: Path) -> None:
    snapshot = tmp_path / "latest_graph.json"
    snapshot.write_text(
        json.dumps(
            {
                "generated_at": "2026-02-25T00:00:00Z",
                "nodes": [
                    {"id": "s1", "label": "LogicStep", "text": "step one"},
                    {"id": "k1", "label": "KnowledgeEntity", "text": "entity"},
                ],
                "edges": [
                    {"source": "s1", "target": "k1", "type": "EXPLAINS", "weight": 1.0},
                    {"source": "s1", "target": "k9", "type": "EXPLAINS", "weight": 0.6},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fusion_service, "_snapshot_file", lambda: snapshot)

    out = fusion_service.get_fusion_graph(limit_nodes=10, limit_edges=10)

    assert out["source"] == "snapshot"
    assert len(out["nodes"]) == 2
    assert len(out["edges"]) == 1
    assert out["edges"][0]["source"] == "s1"
    assert out["edges"][0]["target"] == "k1"
