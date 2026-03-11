from __future__ import annotations

import importlib


def _projection_module():
    try:
        return importlib.import_module("app.community.projection")
    except ModuleNotFoundError:
        return None


class _FakeProjectionClient:
    def list_textbook_entities_for_fusion(self, textbook_id=None, limit: int = 50000):  # noqa: ANN001
        return [
            {
                "entity_id": "ke-1",
                "name": "Finite Element Method",
                "entity_type": "method",
                "description": "A numerical discretization method.",
                "source_chapter_id": "tb:1:ch001",
            },
            {
                "entity_id": "ke-2",
                "name": "Mesh Quality",
                "entity_type": "concept",
                "description": "Mesh quality affects solver stability.",
                "source_chapter_id": "tb:1:ch001",
            },
        ]

    def list_textbook_relations_for_fusion(self, textbook_id=None, limit: int = 100000):  # noqa: ANN001
        return [
            {
                "start_id": "ke-1",
                "end_id": "ke-2",
                "rel_type": "RELATES_TO",
            }
        ]

    def list_logic_steps_for_fusion(self, paper_id=None, limit: int = 50000):  # noqa: ANN001
        return [
            {
                "logic_step_id": "ls-1",
                "paper_id": "paper-1",
                "paper_source": "paper-A",
                "step_type": "Method",
                "summary": "Uses finite element discretization.",
            }
        ]

    def list_claims_for_fusion(self, paper_id=None, limit: int = 50000):  # noqa: ANN001
        return [
            {
                "claim_id": "cl-1",
                "paper_id": "paper-1",
                "paper_source": "paper-A",
                "step_type": "Method",
                "text": "Finite element discretization improves stability.",
                "confidence": 0.91,
            }
        ]


def test_build_global_projection_emits_only_allowed_nodes_and_edges() -> None:
    projection = _projection_module()
    assert projection is not None, "Expected app.community.projection to exist for the global community migration."
    assert hasattr(projection, "build_global_projection"), "Expected build_global_projection() to be implemented."

    graph = projection.build_global_projection(client=_FakeProjectionClient())

    assert graph.__class__.__name__ == "MultiDiGraph"
    assert sorted(graph.nodes) == ["cl-1", "ke-1", "ke-2", "ls-1"]

    labels = {node_id: graph.nodes[node_id].get("label") for node_id in graph.nodes}
    assert labels == {
        "ke-1": "KnowledgeEntity",
        "ke-2": "KnowledgeEntity",
        "cl-1": "Claim",
        "ls-1": "LogicStep",
    }

    properties = {node_id: graph.nodes[node_id].get("properties") for node_id in graph.nodes}
    assert properties["ke-1"]["name"] == "Finite Element Method"
    assert properties["cl-1"]["name"] == "Finite element discretization improves stability."
    assert properties["ls-1"]["name"] == "Uses finite element discretization."

    relations = {
        (source, target, data.get("relation"))
        for source, target, data in graph.edges(data=True)
    }
    assert relations == {
        ("ke-1", "ke-2", "RELATES_TO"),
        ("ls-1", "cl-1", "HAS_CLAIM"),
    }
