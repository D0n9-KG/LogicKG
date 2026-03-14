from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routers.community as community_router
from app.community.overview_graph import build_overview_community_graph


def test_build_overview_community_graph_caps_nodes_and_balances_member_kinds() -> None:
    communities = [
        {
            "community_id": "gc:alpha",
            "title": "Alpha stability",
            "summary": "Claims about alpha stability.",
            "member_count": 5,
            "keywords": ["alpha", "stability", "fem"],
        },
        {
            "community_id": "gc:beta",
            "title": "Beta transfer",
            "summary": "Logic about beta transfer.",
            "member_count": 4,
            "keywords": ["beta", "stability"],
        },
        {
            "community_id": "gc:gamma",
            "title": "Gamma tails",
            "summary": "Lower-priority tail cluster.",
            "member_count": 1,
            "keywords": ["gamma"],
        },
    ]
    members_by_community = {
        "gc:alpha": [
            {
                "member_id": "claim-1",
                "member_kind": "Claim",
                "text": "Alpha claim with the strongest signal.",
                "paper_id": "paper-1",
                "paper_source": "P-001",
                "paper_title": "Alpha Study",
                "step_type": "Method",
            },
            {
                "member_id": "logic-1",
                "member_kind": "LogicStep",
                "text": "Alpha logic step that explains the method.",
                "paper_id": "paper-1",
                "paper_source": "P-001",
                "paper_title": "Alpha Study",
                "step_type": "Method",
            },
            {
                "member_id": "entity-1",
                "member_kind": "KnowledgeEntity",
                "text": "Finite Element Method",
            },
        ],
        "gc:beta": [
            {
                "member_id": "claim-2",
                "member_kind": "Claim",
                "text": "Beta claim that keeps the cross-community bridge alive.",
                "paper_id": "paper-2",
                "paper_source": "P-002",
            },
            {
                "member_id": "entity-2",
                "member_kind": "KnowledgeEntity",
                "text": "Transfer learning",
            },
        ],
        "gc:gamma": [
            {
                "member_id": "claim-3",
                "member_kind": "Claim",
                "text": "Gamma tail content.",
                "paper_id": "paper-3",
                "paper_source": "P-003",
            }
        ],
    }

    graph = build_overview_community_graph(
        communities,
        members_by_community,
        community_limit=2,
        member_limit_per_community=2,
        max_nodes=6,
        max_edges=8,
        max_community_links=4,
    )

    node_ids = {row["id"] for row in graph["nodes"]}
    assert node_ids == {
        "community:gc:alpha",
        "community:gc:beta",
        "claim:claim-1",
        "logic:logic-1",
        "claim:claim-2",
        "entity:entity-2",
    }
    assert "entity:entity-1" not in node_ids
    assert "community:gc:gamma" not in node_ids
    assert any(
        row["source"] == "community:gc:alpha"
        and row["target"] == "community:gc:beta"
        and row["kind"] == "similar"
        for row in graph["edges"]
    )
    assert graph["stats"]["truncated"] is True
    assert graph["stats"]["hidden_communities"] == 1
    assert graph["stats"]["hidden_members"] == 2


class _FakeNeo4jClient:
    def __init__(self, uri: str, user: str, password: str) -> None:  # noqa: ARG002
        pass

    def __enter__(self) -> "_FakeNeo4jClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def list_global_community_rows(self, limit: int = 50000) -> list[dict]:
        return [
            {
                "community_id": "gc:alpha",
                "title": "Alpha stability",
                "summary": "Claims about alpha stability.",
                "member_count": 5,
                "keywords": ["alpha", "stability", "fem"],
            },
            {
                "community_id": "gc:beta",
                "title": "Beta transfer",
                "summary": "Logic about beta transfer.",
                "member_count": 4,
                "keywords": ["beta", "stability"],
            },
        ][:limit]

    def list_global_community_members(self, community_id: str, limit: int = 200) -> list[dict]:
        rows = {
            "gc:alpha": [
                {
                    "member_id": "claim-1",
                    "member_kind": "Claim",
                    "text": "Alpha claim with the strongest signal.",
                    "paper_id": "paper-1",
                    "paper_source": "P-001",
                    "paper_title": "Alpha Study",
                    "step_type": "Method",
                },
                {
                    "member_id": "logic-1",
                    "member_kind": "LogicStep",
                    "text": "Alpha logic step that explains the method.",
                    "paper_id": "paper-1",
                    "paper_source": "P-001",
                    "paper_title": "Alpha Study",
                    "step_type": "Method",
                },
                {
                    "member_id": "entity-1",
                    "member_kind": "KnowledgeEntity",
                    "text": "Finite Element Method",
                },
            ],
            "gc:beta": [
                {
                    "member_id": "claim-2",
                    "member_kind": "Claim",
                    "text": "Beta claim that keeps the cross-community bridge alive.",
                    "paper_id": "paper-2",
                    "paper_source": "P-002",
                },
                {
                    "member_id": "entity-2",
                    "member_kind": "KnowledgeEntity",
                    "text": "Transfer learning",
                },
            ],
        }
        return rows[community_id][:limit]


def test_community_overview_graph_endpoint_returns_capped_graph(monkeypatch) -> None:
    monkeypatch.setattr(community_router, "Neo4jClient", _FakeNeo4jClient)

    app = FastAPI()
    app.include_router(community_router.router)
    client = TestClient(app)

    res = client.get(
        "/community/overview-graph",
        params={
            "community_limit": 2,
            "member_limit_per_community": 2,
            "max_nodes": 6,
            "max_edges": 8,
        },
    )
    assert res.status_code == 200, res.text
    payload = res.json()

    assert payload["stats"]["community_total"] == 2
    assert len(payload["nodes"]) == 6
    assert len(payload["edges"]) <= 8
    assert any(node["id"] == "community:gc:alpha" and node["kind"] == "community" for node in payload["nodes"])
    assert any(node["id"] == "claim:claim-1" and node["cluster_key"] == "community:gc:alpha" for node in payload["nodes"])
    assert any(
        node["id"] == "claim:claim-1"
        and node.get("paper_source") == "P-001"
        and node.get("paper_title") == "Alpha Study"
        and node.get("step_type") == "Method"
        for node in payload["nodes"]
    )
    assert any(
        edge["source"] == "community:gc:alpha"
        and edge["target"] == "community:gc:beta"
        and edge["kind"] == "similar"
        for edge in payload["edges"]
    )
