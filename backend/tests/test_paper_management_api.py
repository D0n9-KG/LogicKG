from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routers.papers as papers_router
from app.graph.neo4j_client import Neo4jClient


class _FakeNeo4jClient:
    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[tuple[int, str | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def list_papers_for_management(self, limit: int = 200, query: str | None = None) -> list[dict]:
        self.calls.append((limit, query))
        return [
            {
                "paper_id": "doi:10.1234/test",
                "paper_source": "attention-source",
                "title": "Readable Title",
                "display_title": "Readable Title",
                "doi": "10.1234/test",
                "year": 2024,
                "ingested": True,
                "deletable": True,
                "collections": [{"collection_id": "c-1", "name": "Transformers"}],
            },
            {
                "paper_id": "doi:10.1234/stub",
                "paper_source": "metadata-source",
                "title": None,
                "display_title": "Metadata Only Title",
                "doi": "10.1234/stub",
                "year": None,
                "ingested": False,
                "deletable": False,
                "collections": [],
            },
        ]


def test_papers_manage_includes_ingested_and_metadata_only(monkeypatch) -> None:
    fake = _FakeNeo4jClient()
    monkeypatch.setattr(papers_router, "Neo4jClient", lambda *args, **kwargs: fake)

    app = FastAPI()
    app.include_router(papers_router.router)
    client = TestClient(app)

    response = client.get("/papers/manage", params={"limit": 20, "q": "attention"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["papers"][0]["display_title"] == "Readable Title"
    assert payload["papers"][0]["collections"] == [{"collection_id": "c-1", "name": "Transformers"}]
    assert {row["ingested"] for row in payload["papers"]} == {True, False}
    assert any(row["deletable"] is False for row in payload["papers"])
    assert fake.calls == [(20, "attention")]


class _CaptureSession:
    def __init__(self) -> None:
        self.last_query = ""
        self.last_params: dict[str, object] = {}

    def run(self, query: str, parameters: dict[str, object] | None = None, **params):
        self.last_query = str(query)
        self.last_params = dict(parameters or {})
        self.last_params.update(params)
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _CaptureDriver:
    def __init__(self, session: _CaptureSession) -> None:
        self._session = session

    def session(self):
        return self._session

    def close(self):
        return None


def test_list_papers_for_management_query_includes_collections_and_display_title_fallback() -> None:
    fake_session = _CaptureSession()
    client = object.__new__(Neo4jClient)
    client._driver = _CaptureDriver(fake_session)

    client.list_papers_for_management(limit=50, query="attention")

    assert "OPTIONAL MATCH (co:Collection)-[:HAS_PAPER]->(p)" in fake_session.last_query
    assert "[x IN cos WHERE x IS NOT NULL | {collection_id: x.collection_id, name: x.name}] AS collections" in fake_session.last_query
    assert "WHEN trim(coalesce(p.paper_source, '')) <> '' THEN p.paper_source" in fake_session.last_query
    assert "WHEN trim(coalesce(p.doi, '')) <> '' THEN p.doi" not in fake_session.last_query
    assert fake_session.last_params == {"limit": 50, "search": "attention"}
