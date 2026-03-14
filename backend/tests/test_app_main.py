from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import anyio

from app.main import app, register_task_handlers
from app.tasks.models import TaskType


class _FakeTaskManager:
    def __init__(self) -> None:
        self.registered: dict[TaskType, object] = {}

    def register(self, task_type: TaskType, handler: object) -> None:
        self.registered[task_type] = handler


def test_register_task_handlers_registers_all_expected_task_types():
    manager = _FakeTaskManager()

    register_task_handlers(manager)

    assert set(manager.registered) == {
        TaskType.ingest_path,
        TaskType.ingest_upload_ready,
        TaskType.ingest_textbook_upload_ready,
        TaskType.upload_replace,
        TaskType.delete_papers_batch,
        TaskType.delete_textbooks_batch,
        TaskType.rebuild_paper,
        TaskType.rebuild_faiss,
        TaskType.rebuild_all,
        TaskType.rebuild_fusion,
        TaskType.rebuild_global_communities,
        TaskType.cleanup_legacy_propositions,
        TaskType.rebuild_similarity,
        TaskType.update_similarity_paper,
        TaskType.ingest_textbook,
    }


def test_app_uses_lifespan_instead_of_deprecated_startup_hooks():
    assert app.router.on_startup == []


def test_lifespan_applies_profile_settings_on_startup(monkeypatch):
    import app.main as main_module

    applied: list[bool] = []

    monkeypatch.setattr(main_module, "apply_profile_to_settings", lambda: applied.append(True) or {})
    monkeypatch.setattr(main_module.task_manager, "start", lambda: None)
    monkeypatch.setattr(main_module.task_manager, "stop", lambda: None)

    async def _exercise() -> None:
        async with main_module.lifespan(main_module.app):
            pass

    anyio.run(_exercise)

    assert applied == [True]


def test_importing_app_main_does_not_emit_faiss_swig_warnings():
    backend_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-W", "default", "-c", "import app.main"],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "SwigPyPacked" not in result.stderr
    assert "SwigPyObject" not in result.stderr
    assert "swigvarlink" not in result.stderr


def test_app_exposes_global_community_routes():
    routes = {
        (getattr(route, "path", None), tuple(sorted(getattr(route, "methods", set()))))
        for route in app.routes
    }

    assert ("/community/list", ("GET",)) in routes
    assert ("/community/{community_id}", ("GET",)) in routes
    assert ("/community/overview-graph", ("GET",)) in routes
    assert ("/tasks/delete/papers", ("POST",)) in routes
    assert ("/tasks/delete/textbooks", ("POST",)) in routes
    assert ("/tasks/rebuild/community", ("POST",)) in routes
    assert ("/tasks/cleanup/propositions", ("POST",)) in routes
    assert ("/tasks/rebuild/evolution", ("POST",)) not in routes
    assert ("/discovery/batch", ("POST",)) not in routes
