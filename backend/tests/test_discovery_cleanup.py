from __future__ import annotations

import json

import pytest


def test_cleanup_legacy_discovery_artifacts_removes_discovery_residue(monkeypatch, tmp_path):
    import app.ingest.rebuild as rebuild_mod
    import app.ops_config_store as config_store
    import app.tasks.store as tasks_store

    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(rebuild_mod.settings, "storage_dir", str(storage_dir), raising=False)
    monkeypatch.setattr(tasks_store.settings, "storage_dir", str(storage_dir), raising=False)
    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")
    legacy_policy = tmp_path / "legacy" / "prompt_policy_bandit.json"
    monkeypatch.setattr(rebuild_mod, "_legacy_discovery_policy_paths", lambda: [legacy_policy])

    config_path = tmp_path / "config_center.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "modules": {
                    "discovery": {"domain": "granular_flow"},
                    "similarity": {"group_clustering_method": "hybrid", "group_clustering_threshold": 0.85},
                },
            }
        ),
        encoding="utf-8",
    )

    active_policy = rebuild_mod._storage_dir() / "discovery" / "prompt_policy_bandit.json"
    active_policy.parent.mkdir(parents=True, exist_ok=True)
    active_policy.write_text("{}", encoding="utf-8")

    legacy_policy.parent.mkdir(parents=True, exist_ok=True)
    legacy_policy.write_text("{}", encoding="utf-8")

    tasks_dir = tasks_store.tasks_dir()
    (tasks_dir / "discovery-task.json").write_text(
        json.dumps({"task_id": "discovery-task", "type": "discovery_batch", "status": "succeeded"}),
        encoding="utf-8",
    )

    class _FakeNeo4jClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def clear_legacy_discovery_artifacts(self):
            return {
                "deleted_labels": {
                    "KnowledgeGap": 1,
                    "ResearchQuestion": 2,
                    "ResearchQuestionCandidate": 0,
                    "FeedbackRecord": 3,
                    "KnowledgeGapSeed": 4,
                }
            }

        def drop_legacy_discovery_schema(self):
            return {"dropped_constraints": 5, "dropped_indexes": 6}

    monkeypatch.setattr(rebuild_mod, "Neo4jClient", _FakeNeo4jClient)

    cleanup = getattr(rebuild_mod, "cleanup_legacy_discovery_artifacts", None)
    if cleanup is None:
        pytest.fail("cleanup_legacy_discovery_artifacts is missing")

    report = cleanup()

    assert report["ok"] is True
    assert report["graph"]["deleted_labels"]["KnowledgeGap"] == 1
    assert report["schema"]["dropped_constraints"] == 5
    assert report["tasks"]["deleted_count"] == 1
    assert report["config"]["removed_modules"] == ["discovery"]
    assert report["filesystem"]["active_storage"]["status"] in {"deleted", "missing"}
    assert report["filesystem"]["legacy_prompt_policy"]["status"] in {"deleted", "missing"}


def test_cleanup_reports_partial_failure_but_continues(monkeypatch, tmp_path):
    import app.ingest.rebuild as rebuild_mod
    import app.ops_config_store as config_store
    import app.tasks.store as tasks_store

    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(rebuild_mod.settings, "storage_dir", str(storage_dir), raising=False)
    monkeypatch.setattr(tasks_store.settings, "storage_dir", str(storage_dir), raising=False)
    monkeypatch.setattr(config_store, "_CONFIG_PATH_OVERRIDE", tmp_path / "config_center.json")

    tasks_dir = tasks_store.tasks_dir()
    (tasks_dir / "discovery-task.json").write_text(
        json.dumps({"task_id": "discovery-task", "type": "discovery_batch", "status": "succeeded"}),
        encoding="utf-8",
    )

    class _FailingNeo4jClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def clear_legacy_discovery_artifacts(self):
            raise RuntimeError("graph down")

        def drop_legacy_discovery_schema(self):
            return {"dropped_constraints": 0, "dropped_indexes": 0}

    monkeypatch.setattr(rebuild_mod, "Neo4jClient", _FailingNeo4jClient)

    cleanup = getattr(rebuild_mod, "cleanup_legacy_discovery_artifacts", None)
    if cleanup is None:
        pytest.fail("cleanup_legacy_discovery_artifacts is missing")

    report = cleanup()

    assert report["ok"] is False
    assert report["graph"]["status"] == "error"
    assert report["tasks"]["status"] == "ok"
    assert report["tasks"]["deleted_count"] == 1
