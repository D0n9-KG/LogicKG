from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
        TaskType.upload_replace,
        TaskType.rebuild_paper,
        TaskType.rebuild_faiss,
        TaskType.rebuild_all,
        TaskType.rebuild_fusion,
        TaskType.rebuild_global_communities,
        TaskType.rebuild_similarity,
        TaskType.update_similarity_paper,
        TaskType.ingest_textbook,
        TaskType.discovery_batch,
    }


def test_app_uses_lifespan_instead_of_deprecated_startup_hooks():
    assert app.router.on_startup == []


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
    assert ("/tasks/rebuild/community", ("POST",)) in routes
    assert ("/tasks/rebuild/evolution", ("POST",)) not in routes
