from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routers.graph as graph_router


class _FakeNeo4jClient:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self.uri = uri
        self.user = user
        self.password = password

    def __enter__(self) -> "_FakeNeo4jClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def list_papers(self, limit: int = 50, collection_id: str | None = None) -> list[dict]:
        return [
            {
                "paper_id": "p-1",
                "paper_source": "paper-1",
                "title": "Paper 1",
                "collections": [],
            }
        ]

    def count_papers(self, collection_id: str | None = None) -> int:
        return 33470 if not collection_id else 12


def test_graph_papers_endpoint_returns_total_count(monkeypatch) -> None:
    monkeypatch.setattr(graph_router, "Neo4jClient", _FakeNeo4jClient)

    app = FastAPI()
    app.include_router(graph_router.router)
    client = TestClient(app)

    res = client.get("/graph/papers", params={"limit": 1})

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["total_count"] == 33470
    assert len(payload["papers"]) == 1


def test_graph_papers_endpoint_counts_selected_collection(monkeypatch) -> None:
    monkeypatch.setattr(graph_router, "Neo4jClient", _FakeNeo4jClient)

    app = FastAPI()
    app.include_router(graph_router.router)
    client = TestClient(app)

    res = client.get("/graph/papers", params={"limit": 1, "collection_id": "c1"})

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["total_count"] == 12
    assert len(payload["papers"]) == 1
