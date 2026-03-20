from __future__ import annotations

import importlib
import io
import json

import pytest


class _FakeProcess:
    def __init__(self, stdout_lines: list[str], *, stderr: str = "", returncode: int = 0) -> None:
        payload = "\n".join(stdout_lines)
        if payload:
            payload += "\n"
        self.stdout = io.StringIO(payload)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode


def test_handle_rebuild_global_communities_runs_in_subprocess_and_relays_events(monkeypatch: pytest.MonkeyPatch) -> None:
    handlers = importlib.import_module("app.tasks.handlers")

    monkeypatch.setattr(handlers, "_load_payload", lambda task_id: {})
    popen_calls: list[dict[str, object]] = []

    fake_lines = [
        json.dumps({"event": "progress", "stage": "community:projection", "progress": 0.25, "message": "Building projection"}),
        json.dumps({"event": "log", "line": "global community projection: nodes=2, edges=1"}),
        json.dumps({"event": "progress", "stage": "community:write", "progress": 0.85, "message": "Writing to Neo4j"}),
        json.dumps({"event": "result", "ok": True, "result": {"ok": True, "communities": 1, "keywords": 2}}),
    ]

    def _fake_popen(*args, **kwargs):  # noqa: ANN002, ANN003
        popen_calls.append({"args": args, "kwargs": kwargs})
        return _FakeProcess(fake_lines)

    monkeypatch.setattr(
        "subprocess.Popen",
        _fake_popen,
    )

    updates: list[tuple[str, float, str | None]] = []
    logs: list[str] = []
    result = handlers.handle_rebuild_global_communities(
        "task-1",
        lambda stage, progress, message=None: updates.append((stage, float(progress), message)),
        logs.append,
    )

    assert result == {"ok": True, "communities": 1, "keywords": 2}
    assert ("community:init", 0.02, "Rebuilding global communities") in updates
    assert ("community:projection", 0.25, "Building projection") in updates
    assert ("community:write", 0.85, "Writing to Neo4j") in updates
    assert "global community projection: nodes=2, edges=1" in logs
    assert popen_calls
    env = popen_calls[0]["kwargs"].get("env")
    assert isinstance(env, dict)
    assert env.get("OPENBLAS_NUM_THREADS") == "64"
    assert env.get("OMP_NUM_THREADS") == "64"
    assert env.get("MKL_NUM_THREADS") == "64"


def test_handle_rebuild_global_communities_surfaces_subprocess_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    handlers = importlib.import_module("app.tasks.handlers")

    monkeypatch.setattr(handlers, "_load_payload", lambda task_id: {})
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess([], stderr="Segmentation fault", returncode=-11),
    )

    with pytest.raises(RuntimeError, match="subprocess exited with code -11"):
        handlers.handle_rebuild_global_communities("task-1", lambda *args, **kwargs: None, lambda *args, **kwargs: None)
