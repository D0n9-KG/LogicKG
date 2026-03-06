from __future__ import annotations

import json
import os
from pathlib import Path

from app.settings import settings
from app.tasks.models import TaskRecord, TaskStatus


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def tasks_dir() -> Path:
    # backend/storage/tasks
    root = _backend_root()
    p = root / settings.storage_dir / "tasks"
    p.mkdir(parents=True, exist_ok=True)
    return p


def task_path(task_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in task_id)
    return tasks_dir() / f"{safe}.json"


def save_task(task: TaskRecord) -> None:
    p = task_path(task.task_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def load_task(task_id: str) -> TaskRecord:
    p = task_path(task_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return TaskRecord.from_dict(data)
    except FileNotFoundError as exc:
        # Avoid leaking filesystem paths into API error responses (confusing for users).
        raise FileNotFoundError(f"Task not found: {task_id}") from exc


_FINISHED = {TaskStatus.succeeded, TaskStatus.failed, TaskStatus.canceled}


def list_tasks(limit: int = 50, keep_finished: int = 10, prune_finished: bool = True) -> list[TaskRecord]:
    limit = int(limit or 0)
    if limit <= 0:
        return []
    keep_finished = int(keep_finished or 0)
    if keep_finished < 0:
        keep_finished = 0

    items = sorted(tasks_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    parsed: list[tuple[Path, TaskRecord]] = []
    for p in items:
        try:
            parsed.append((p, TaskRecord.from_dict(json.loads(p.read_text(encoding="utf-8")))))
        except Exception:
            continue

    active: list[tuple[Path, TaskRecord]] = []
    finished: list[tuple[Path, TaskRecord]] = []
    for p, t in parsed:
        if t.status in _FINISHED:
            finished.append((p, t))
        else:
            active.append((p, t))

    if prune_finished and len(finished) > keep_finished:
        for p, _ in finished[keep_finished:]:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        finished = finished[:keep_finished]

    by_path: dict[Path, TaskRecord] = {p: t for p, t in active + finished}
    kept = []
    for p in items:
        t = by_path.get(p)
        if t is not None:
            kept.append(t)
        if len(kept) >= limit:
            break
    return kept
