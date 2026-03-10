from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routers.textbooks as textbooks_router


class _FakeNeo4jClient:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self.uri = uri
        self.user = user
        self.password = password

    def __enter__(self) -> "_FakeNeo4jClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def get_textbook_graph_snapshot(self, textbook_id: str, entity_limit: int = 260, edge_limit: int = 520) -> dict:
        return {
            "scope": "textbook",
            "textbook": {"textbook_id": textbook_id, "title": "Textbook"},
            "chapters": [{"chapter_id": "ch-1", "chapter_num": 1, "title": "Chapter 1", "entity_count": 2, "relation_count": 1}],
            "entities": [{"entity_id": "e-1", "name": "Bubble", "entity_type": "concept", "source_chapter_id": "ch-1"}],
            "relations": [{"source_id": "e-1", "target_id": "e-1", "rel_type": "self"}],
            "communities": [{"community_id": "c-1", "label": "Cluster 1", "member_ids": ["e-1"], "size": 1, "source": "derived"}],
            "stats": {"entity_total": entity_limit, "relation_total": edge_limit, "community_total": 1, "truncated": False},
        }

    def get_chapter_graph_snapshot(self, chapter_id: str, entity_limit: int = 220, edge_limit: int = 420) -> dict:
        return {
            "scope": "chapter",
            "chapter": {"chapter_id": chapter_id, "chapter_num": 1, "title": "Chapter 1"},
            "entities": [{"entity_id": "e-1", "name": "Bubble", "entity_type": "concept", "source_chapter_id": chapter_id}],
            "relations": [{"source_id": "e-1", "target_id": "e-1", "rel_type": "self"}],
            "communities": [{"community_id": "c-1", "label": "Cluster 1", "member_ids": ["e-1"], "size": 1, "source": "derived"}],
            "stats": {"entity_total": entity_limit, "relation_total": edge_limit, "community_total": 1, "truncated": False},
        }


def test_textbook_graph_snapshot_endpoint_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(textbooks_router, "Neo4jClient", _FakeNeo4jClient)

    app = FastAPI()
    app.include_router(textbooks_router.router)
    client = TestClient(app)

    res = client.get("/textbooks/tb-1/graph", params={"entity_limit": 12, "edge_limit": 18})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scope"] == "textbook"
    assert payload["textbook"]["textbook_id"] == "tb-1"
    assert payload["chapters"][0]["chapter_id"] == "ch-1"
    assert payload["stats"]["entity_total"] == 12
    assert payload["stats"]["relation_total"] == 18


def test_chapter_graph_snapshot_endpoint_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(textbooks_router, "Neo4jClient", _FakeNeo4jClient)

    app = FastAPI()
    app.include_router(textbooks_router.router)
    client = TestClient(app)

    res = client.get("/textbooks/tb-1/chapters/ch-1/graph", params={"entity_limit": 8, "edge_limit": 10})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["scope"] == "chapter"
    assert payload["chapter"]["chapter_id"] == "ch-1"
    assert payload["stats"]["entity_total"] == 8
    assert payload["stats"]["relation_total"] == 10
