from __future__ import annotations

import importlib

from app.graph.neo4j_client import Neo4jClient


class _Result:
    def __init__(self, row: dict | None = None) -> None:
        self._row = row or {"cnt": 0}

    def single(self):
        return self._row

    def __iter__(self):
        return iter(())


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **params):
        self.calls.append((str(query), dict(params)))
        if "RETURN count(DISTINCT gc) AS cnt" in str(query):
            return _Result({"cnt": 1})
        if "RETURN count(hk) AS cnt" in str(query):
            return _Result({"cnt": 2})
        if "RETURN count(im) AS cnt" in str(query):
            return _Result({"cnt": 2})
        if "count(gc) AS deleted_communities" in str(query):
            return _Result(
                {
                    "deleted_communities": 1,
                    "deleted_keywords": 2,
                    "deleted_memberships": 2,
                    "deleted_keyword_edges": 2,
                }
            )
        if "RETURN gc.community_id AS community_id" in str(query):
            return [
                {
                    "community_id": "gc:demo",
                    "title": "Finite element stability",
                    "summary": "Claims and textbook entities about FEM stability.",
                    "member_count": 2,
                    "keywords": ["finite element", "stability"],
                }
            ]
        if "RETURN member_id AS member_id" in str(query):
            return [
                {"member_id": "cl-1", "member_kind": "Claim", "text": "FEM improves stability."},
                {"member_id": "ke-1", "member_kind": "KnowledgeEntity", "text": "Finite Element Method"},
            ]
        return _Result({"cnt": 0})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self):
        return self._session

    def close(self):
        return None


def _client_with_fake_driver(fake_session: _FakeSession) -> Neo4jClient:
    client = object.__new__(Neo4jClient)
    client._driver = _FakeDriver(fake_session)
    return client


def test_global_community_writer_helpers_use_global_labels_and_edges() -> None:
    fake_session = _FakeSession()
    client = _client_with_fake_driver(fake_session)

    assert hasattr(client, "clear_global_communities"), "Expected clear_global_communities() to exist."
    assert hasattr(client, "upsert_global_communities"), "Expected upsert_global_communities() to exist."
    assert hasattr(client, "upsert_global_keywords"), "Expected upsert_global_keywords() to exist."
    assert hasattr(client, "replace_global_memberships"), "Expected replace_global_memberships() to exist."

    deleted = client.clear_global_communities()
    written = client.upsert_global_communities(
        [
            {
                "community_id": "gc:demo",
                "title": "Finite element stability",
                "summary": "Claims and textbook entities about FEM stability.",
                "confidence": 0.88,
                "member_count": 2,
                "version": "v1",
            }
        ]
    )
    keyword_edges = client.upsert_global_keywords(
        [
            {
                "community_id": "gc:demo",
                "keyword_id": "gk:demo:1",
                "keyword": "finite element",
                "rank": 1,
                "weight": 0.82,
            },
            {
                "community_id": "gc:demo",
                "keyword_id": "gk:demo:2",
                "keyword": "stability",
                "rank": 2,
                "weight": 0.71,
            },
        ]
    )
    membership_edges = client.replace_global_memberships(
        [
            {"community_id": "gc:demo", "member_id": "cl-1", "member_kind": "Claim", "weight": 0.91},
            {"community_id": "gc:demo", "member_id": "ke-1", "member_kind": "KnowledgeEntity", "weight": 0.73},
        ]
    )

    assert deleted["deleted_communities"] == 1
    assert written == 1
    assert keyword_edges == 2
    assert membership_edges == 2

    queries = "\n".join(query for query, _ in fake_session.calls)
    assert "GlobalCommunity" in queries
    assert "GlobalKeyword" in queries
    assert "IN_GLOBAL_COMMUNITY" in queries
    assert "HAS_GLOBAL_KEYWORD" in queries


def test_global_community_read_helpers_return_keywords_and_members() -> None:
    fake_session = _FakeSession()
    client = _client_with_fake_driver(fake_session)

    assert hasattr(client, "list_global_community_rows"), "Expected list_global_community_rows() to exist."
    assert hasattr(client, "list_global_community_members"), "Expected list_global_community_members() to exist."

    rows = client.list_global_community_rows(limit=20)
    members = client.list_global_community_members("gc:demo", limit=10)

    assert rows == [
        {
            "community_id": "gc:demo",
            "title": "Finite element stability",
            "summary": "Claims and textbook entities about FEM stability.",
            "member_count": 2,
            "keywords": ["finite element", "stability"],
        }
    ]
    assert members == [
        {"member_id": "cl-1", "member_kind": "Claim", "text": "FEM improves stability."},
        {"member_id": "ke-1", "member_kind": "KnowledgeEntity", "text": "Finite Element Method"},
    ]


def test_legacy_proposition_cleanup_helper_deletes_groups_nodes_and_relation_edges() -> None:
    class _CleanupSession(_FakeSession):
        def run(self, query: str, **params):
            self.calls.append((str(query), dict(params)))
            if "deleted_proposition_groups" in str(query):
                return _Result(
                    {
                        "deleted_proposition_groups": 2,
                        "deleted_propositions": 3,
                        "deleted_relation_edges": 4,
                    }
                )
            return _Result({"cnt": 0})

    fake_session = _CleanupSession()
    client = _client_with_fake_driver(fake_session)

    assert hasattr(
        client,
        "clear_legacy_proposition_artifacts",
    ), "Expected clear_legacy_proposition_artifacts() to exist."

    deleted = client.clear_legacy_proposition_artifacts()

    assert deleted == {
        "deleted_proposition_groups": 2,
        "deleted_propositions": 3,
        "deleted_relation_edges": 4,
    }

    queries = "\n".join(query for query, _ in fake_session.calls)
    assert "PropositionGroup" in queries
    assert "Proposition" in queries
    assert "SUPPORTS" in queries
    assert "CHALLENGES" in queries
    assert "SUPERSEDES" in queries


def test_legacy_proposition_schema_cleanup_helper_drops_constraints_and_indexes() -> None:
    fake_session = _FakeSession()
    client = _client_with_fake_driver(fake_session)

    dropped = client.drop_legacy_proposition_schema()

    assert dropped == {
        "dropped_constraints": 3,
        "dropped_indexes": 2,
    }

    queries = "\n".join(query for query, _ in fake_session.calls)
    assert "DROP CONSTRAINT proposition_id_unique IF EXISTS" in queries
    assert "DROP CONSTRAINT proposition_key_unique IF EXISTS" in queries
    assert "DROP CONSTRAINT proposition_group_id_unique IF EXISTS" in queries
    assert "DROP INDEX proposition_state IF EXISTS" in queries
    assert "DROP INDEX proposition_score IF EXISTS" in queries


def test_rebuild_global_communities_passes_projection_limits_from_settings(monkeypatch) -> None:
    service = importlib.import_module("app.community.service")

    captured: dict[str, object] = {}

    class _Graph:
        def number_of_nodes(self) -> int:
            return 2

        def number_of_edges(self) -> int:
            return 1

    class _FakeClient:
        def ensure_schema(self) -> None:
            captured["ensure_schema"] = True

        def clear_global_communities(self) -> dict[str, int]:
            return {"deleted_communities": 0}

        def upsert_global_communities(self, items: list[dict]) -> int:
            captured["communities"] = list(items)
            return len(items)

        def upsert_global_keywords(self, items: list[dict]) -> int:
            captured["keywords"] = list(items)
            return len(items)

        def replace_global_memberships(self, items: list[dict]) -> int:
            captured["memberships"] = list(items)
            return len(items)

    class _FakeNeo4jClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.client = _FakeClient()

        def __enter__(self):
            return self.client

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_projection(*, client, node_limit, edge_limit):  # noqa: ANN001
        captured["projection_client"] = client
        captured["node_limit"] = node_limit
        captured["edge_limit"] = edge_limit
        return _Graph()

    def _fake_run_tree_comm(graph, *, top_keywords, version):  # noqa: ANN001
        captured["run_tree_comm_graph"] = graph
        captured["top_keywords"] = top_keywords
        captured["version"] = version
        return {
            "communities": [
                {
                    "community_id": "gc:demo",
                    "title": "Finite element stability",
                    "summary": "TreeComm summary",
                    "confidence": 1.0,
                    "member_count": 2,
                    "member_ids": ["ke-1", "cl-1"],
                    "version": version,
                    "built_at": "2026-03-11T00:00:00+00:00",
                }
            ],
            "keywords": [
                {
                    "community_id": "gc:demo",
                    "keyword_id": "gk:demo:1",
                    "keyword": "finite element",
                    "rank": 1,
                    "weight": 1.0,
                }
            ],
        }

    monkeypatch.setattr(service, "Neo4jClient", _FakeNeo4jClient)
    monkeypatch.setattr(service, "build_global_projection", _fake_projection)
    monkeypatch.setattr(service, "run_tree_comm", _fake_run_tree_comm)
    monkeypatch.setattr(service.settings, "global_community_max_nodes", 12)
    monkeypatch.setattr(service.settings, "global_community_max_edges", 34)
    monkeypatch.setattr(service.settings, "global_community_top_keywords", 3)
    monkeypatch.setattr(service.settings, "global_community_version", "vtest")

    summary = service.rebuild_global_communities()

    assert captured["node_limit"] == 12
    assert captured["edge_limit"] == 34
    assert captured["top_keywords"] == 3
    assert captured["version"] == "vtest"
    assert len(captured["communities"]) == 1
    assert len(captured["keywords"]) == 1
    assert len(captured["memberships"]) == 2
    assert summary["projection_nodes"] == 2
    assert summary["projection_edges"] == 1
    assert summary["communities_written"] == 1
    assert summary["keywords_written"] == 1
    assert summary["memberships_written"] == 2
