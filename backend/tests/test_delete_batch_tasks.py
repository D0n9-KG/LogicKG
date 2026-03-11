from __future__ import annotations

import time

from app.tasks.handlers import run_delete_papers_batch, run_delete_textbooks_batch
from app.tasks.manager import PartialTaskFailure, TaskManager
from app.tasks.models import TaskStatus, TaskType
from app.tasks.store import load_task
import pytest


def test_delete_papers_batch_reports_partial_success_and_rebuild_once(monkeypatch) -> None:
    calls = {"community": 0, "faiss": 0}

    def _fake_delete(paper_id: str, hard_delete: bool = True) -> dict:
        if paper_id == "doi:10.1234/bad":
            raise RuntimeError("boom")
        return {"ok": True, "paper_id": paper_id, "status": "deleted", "skipped": False}

    def _fake_community(*args, **kwargs) -> dict:
        calls["community"] += 1
        return {"communities": 3}

    def _fake_faiss(*args, **kwargs) -> dict:
        calls["faiss"] += 1
        return {"index_size": 9}

    monkeypatch.setattr("app.tasks.handlers.delete_paper_asset", _fake_delete)
    monkeypatch.setattr("app.tasks.handlers.rebuild_global_communities", _fake_community)
    monkeypatch.setattr("app.tasks.handlers.rebuild_global_faiss", _fake_faiss)

    result = run_delete_papers_batch(
        {"paper_ids": ["doi:10.1234/good", "doi:10.1234/bad"], "trigger_rebuild": True},
        lambda stage, progress, message=None: None,
        lambda line: None,
    )

    assert result["deleted_count"] == 1
    assert result["failed_count"] == 1
    assert result["rebuild"]["status"] == "succeeded"
    assert calls == {"community": 1, "faiss": 1}


def test_delete_papers_batch_skips_metadata_only_and_duplicates(monkeypatch) -> None:
    calls = {"delete": 0}

    def _fake_delete(paper_id: str, hard_delete: bool = True) -> dict:
        calls["delete"] += 1
        return {
            "ok": True,
            "paper_id": paper_id,
            "status": "skipped",
            "skipped": True,
            "reason": "metadata_only",
        }

    monkeypatch.setattr("app.tasks.handlers.delete_paper_asset", _fake_delete)

    result = run_delete_papers_batch(
        {"paper_ids": ["doi:10.1234/stub", "doi:10.1234/stub"], "trigger_rebuild": True},
        lambda stage, progress, message=None: None,
        lambda line: None,
    )

    assert result["skipped_count"] == 2
    assert calls["delete"] == 1


def test_delete_papers_batch_rejects_empty_ids_after_normalization(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.tasks.handlers.delete_paper_asset",
        lambda paper_id, hard_delete=True: {"ok": True, "paper_id": paper_id},
    )

    with pytest.raises(ValueError, match="paper_ids"):
        run_delete_papers_batch(
            {"paper_ids": ["", "   "], "trigger_rebuild": True},
            lambda stage, progress, message=None: None,
            lambda line: None,
        )


def test_delete_textbooks_batch_rejects_empty_ids_after_normalization(monkeypatch) -> None:
    monkeypatch.setattr("app.tasks.handlers.delete_textbook_asset", lambda textbook_id: {"ok": True, "textbook_id": textbook_id})

    with pytest.raises(ValueError, match="textbook_ids"):
        run_delete_textbooks_batch(
            {"textbook_ids": ["", "   "], "trigger_rebuild": True},
            lambda stage, progress, message=None: None,
            lambda line: None,
        )


def test_task_manager_preserves_partial_result_when_handler_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.settings.settings.storage_dir", str(tmp_path / "storage"))

    manager = TaskManager()
    partial = {"deleted_count": 1, "failed_count": 0, "skipped_count": 0}

    def _handler(task_id, update, log):  # type: ignore[no-untyped-def]
        raise PartialTaskFailure("global rebuild failed", partial)

    manager.register(TaskType.delete_papers_batch, _handler)
    manager.start()
    try:
        task_id = manager.submit(TaskType.delete_papers_batch, {"paper_ids": ["doi:10.1234/test"]})
        deadline = time.time() + 5
        record = load_task(task_id)
        while time.time() < deadline and record.status not in {TaskStatus.failed, TaskStatus.succeeded}:
            time.sleep(0.05)
            record = load_task(task_id)
    finally:
        manager.stop()
        if manager._thread is not None:
            manager._thread.join(timeout=1)

    assert record.status == TaskStatus.failed
    assert record.result == partial
    assert record.error == "global rebuild failed"
