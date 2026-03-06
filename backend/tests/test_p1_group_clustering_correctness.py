# backend/tests/test_p1_group_clustering_correctness.py
from __future__ import annotations

from typing import Any

import pytest

from app.graph.neo4j_client import Neo4jClient
from app.tasks import clustering_task


class _SingleRowResult:
    def __init__(self, row: dict[str, Any] | None):
        self._row = row

    def single(self):
        return self._row


class _RunHandlerSession:
    def __init__(self, run_handler):
        self.run_handler = run_handler

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query: str, **params):
        return self.run_handler(query, params)


class _RunHandlerDriver:
    def __init__(self, run_handler):
        self.run_handler = run_handler

    def session(self):
        return _RunHandlerSession(self.run_handler)


def test_zero_propositions_branch_cleans_stale_groups(monkeypatch):
    class _FakeSettings:
        neo4j_uri = "bolt://unit"
        neo4j_user = "neo4j"
        neo4j_password = "password"
        group_clustering_threshold = "0.88"

        def effective_embedding_model(self):
            return "text-embedding-3-small"

    class _FakeClient:
        def __init__(self, uri: str, user: str, password: str):
            self._driver = _RunHandlerDriver(lambda query, params: [])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(clustering_task, "Settings", lambda: _FakeSettings())
    monkeypatch.setattr(clustering_task, "Neo4jClient", _FakeClient)
    # Isolate from persisted Config Center profile; fallback should use mocked Settings values.
    monkeypatch.setattr(clustering_task, "merge_similarity_config", lambda _: {})
    monkeypatch.setattr(
        clustering_task,
        "_clear_existing_proposition_groups",
        lambda client: {"groups_deleted": 2, "memberships_deleted": 5},
    )
    monkeypatch.setattr(
        clustering_task,
        "get_embeddings_batch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not embed when no propositions")),
    )
    monkeypatch.setattr(
        clustering_task,
        "cluster_propositions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not cluster when no propositions")),
    )

    out = clustering_task.run_proposition_clustering(task_id="t-no-props")
    assert out["status"] == "completed"
    assert out["groups_created"] == 0
    assert out["propositions_clustered"] == 0
    assert out["groups_deleted"] == 2
    assert out["memberships_deleted"] == 5
    assert out["similarity_threshold"] == pytest.approx(0.88)


def test_count_unique_papers_for_propositions_returns_distinct_count():
    captured: dict[str, Any] = {}

    def _run_handler(query: str, params: dict[str, Any]):
        captured["query"] = query
        captured["params"] = params
        return _SingleRowResult({"paper_count": 3})

    client = Neo4jClient.__new__(Neo4jClient)
    client._driver = _RunHandlerDriver(_run_handler)

    out = clustering_task._count_unique_papers_for_propositions(client, ["prop-1", " ", "prop-2"])
    assert out == 3
    assert captured["params"]["prop_ids"] == ["prop-1", "prop-2"]


def test_threshold_config_is_applied_to_clustering_and_group_write(monkeypatch):
    class _FakeSettings:
        neo4j_uri = "bolt://unit"
        neo4j_user = "neo4j"
        neo4j_password = "password"
        group_clustering_threshold = "0.73"

        def effective_embedding_model(self):
            return "text-embedding-3-small"

    class _FakeClient:
        def __init__(self, uri: str, user: str, password: str):
            # fetch stage: return one proposition row
            self._driver = _RunHandlerDriver(
                lambda query, params: [{"prop_id": "prop-1", "text": "A proposition", "paper_count": 1}]
            )

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    captured = {"cluster_threshold": None, "group_threshold": None}

    def _fake_cluster(embeddings, texts, threshold, method="agglomerative"):
        captured["cluster_threshold"] = threshold
        captured["cluster_method"] = method
        return [
            {
                "member_indices": [0],
                "member_count": 1,
                "avg_similarity": 0.99,
                "representative_text": "A proposition",
            }
        ]

    def _fake_create_group(**kwargs):
        captured["group_threshold"] = kwargs["threshold"]
        return "group-1"

    monkeypatch.setattr(clustering_task, "Settings", lambda: _FakeSettings())
    monkeypatch.setattr(clustering_task, "Neo4jClient", _FakeClient)
    # Isolate from persisted Config Center profile; fallback should use mocked Settings values.
    monkeypatch.setattr(clustering_task, "merge_similarity_config", lambda _: {})
    monkeypatch.setattr(clustering_task, "get_embeddings_batch", lambda texts, model: [[0.1, 0.2, 0.3]])
    monkeypatch.setattr(clustering_task, "cluster_propositions", _fake_cluster)
    monkeypatch.setattr(clustering_task, "_clear_existing_proposition_groups", lambda client: {"groups_deleted": 0, "memberships_deleted": 0})
    monkeypatch.setattr(clustering_task, "_count_unique_papers_for_propositions", lambda client, prop_ids: 1)
    monkeypatch.setattr(clustering_task, "_create_proposition_group", _fake_create_group)

    out = clustering_task.run_proposition_clustering(task_id="t-threshold")
    assert captured["cluster_threshold"] == pytest.approx(0.73)
    assert captured["cluster_method"] == "hybrid"
    assert captured["group_threshold"] == pytest.approx(0.73)
    assert out["groups_created"] == 1
    assert out["similarity_threshold"] == pytest.approx(0.73)
