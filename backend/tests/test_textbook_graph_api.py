from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path

import app.api.routers.textbooks as textbooks_router
import app.ingest.textbook_pipeline as textbook_pipeline


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


def test_textbook_fusion_link_endpoint_submits_global_community_rebuild_task(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_submit(task_type, payload):
        captured["task_type"] = task_type
        captured["payload"] = dict(payload)
        return "task-community-1"

    monkeypatch.setattr(textbooks_router.task_manager, "submit", _fake_submit)

    app = FastAPI()
    app.include_router(textbooks_router.router)
    client = TestClient(app)

    res = client.post("/textbooks/fusion/link", json={"textbook_id": "tb-1"})
    assert res.status_code == 200, res.text

    payload = res.json()
    assert payload == {"task_id": "task-community-1", "task_type": "rebuild_global_communities"}
    assert str(getattr(captured["task_type"], "value", captured["task_type"])) == "rebuild_global_communities"
    assert captured["payload"] == {"textbook_id": "tb-1"}


def test_ingest_textbook_keeps_global_community_rebuild_manual(monkeypatch, tmp_path: Path) -> None:
    source_md = tmp_path / "textbook.md"
    source_md.write_text("# Chapter 1\ncontent", encoding="utf-8")
    graph_json = tmp_path / "graph.json"
    graph_json.write_text("{}", encoding="utf-8")

    class _FakeChapter:
        chapter_num = 1
        title = "Chapter 1"
        body = "# Chapter 1\ncontent"

    class _FakeNeo4jClient:
        def __init__(self, uri: str, user: str, password: str) -> None:
            self.uri = uri
            self.user = user
            self.password = password

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ensure_schema(self) -> None:
            return None

        def upsert_textbook(self, **kwargs) -> None:
            return None

        def upsert_textbook_chapter(self, **kwargs) -> None:
            return None

    monkeypatch.setattr(textbook_pipeline, "Neo4jClient", _FakeNeo4jClient)
    monkeypatch.setattr(textbook_pipeline, "split_textbook_md", lambda md_path: [_FakeChapter()])
    monkeypatch.setattr(textbook_pipeline, "_run_autoyoutu_pipeline", lambda chapter_md_path, output_dir, log: graph_json)
    monkeypatch.setattr(
        textbook_pipeline,
        "import_youtu_graph",
        lambda graph_json_path, textbook_id, chapter_id, neo4j_client: {
            "entity_count": 2,
            "relation_count": 1,
            "community_count": 0,
        },
    )
    monkeypatch.setattr(textbook_pipeline.settings, "storage_dir", str(tmp_path / "storage"), raising=False)

    result = textbook_pipeline.ingest_textbook(
        str(source_md),
        {"title": "Continuum Mechanics", "authors": ["A. Author"]},
    )

    assert result["ok"] is True
    assert "mapped_propositions" not in result
    assert result["global_communities"] == 0
    assert result["global_keywords"] == 0
