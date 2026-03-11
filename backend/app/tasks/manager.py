from __future__ import annotations

import queue
import threading
import uuid
from typing import Any, Callable

from app.tasks.models import TaskRecord, TaskStatus, TaskType, utc_now_iso
from app.tasks.store import list_tasks, load_task, save_task


TaskHandler = Callable[[str, Callable[[str, float, str | None], None], Callable[[str], None]], dict[str, Any]]


class PartialTaskFailure(Exception):
    def __init__(self, message: str, partial_result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.partial_result = partial_result or {}


class TaskManager:
    def __init__(self):
        self._q: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handlers: dict[TaskType, TaskHandler] = {}

    def register(self, task_type: TaskType, handler: TaskHandler) -> None:
        self._handlers[task_type] = handler

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="TaskWorker", daemon=True)
        self._thread.start()

        # Best-effort: re-enqueue tasks that were queued/running before a restart.
        for t in list_tasks(limit=200):
            if t.status in {TaskStatus.queued, TaskStatus.running}:
                # mark previously-running tasks as queued again
                t.status = TaskStatus.queued
                t.stage = "queued"
                t.started_at = None
                t.finished_at = None
                t.error = None
                save_task(t)
                self._q.put(t.task_id)

    def stop(self) -> None:
        self._stop.set()

    def submit(self, task_type: TaskType, payload: dict[str, Any]) -> str:
        task_id = f"{task_type.value}-{uuid.uuid4().hex[:12]}"
        rec = TaskRecord(task_id=task_id, type=task_type, status=TaskStatus.queued, payload=payload)
        save_task(rec)
        self._q.put(task_id)
        return task_id

    def cancel(self, task_id: str) -> bool:
        try:
            t = load_task(task_id)
        except Exception:
            return False
        if t.status in {TaskStatus.succeeded, TaskStatus.failed, TaskStatus.canceled}:
            return False
        t.status = TaskStatus.canceled
        t.stage = "canceled"
        t.finished_at = utc_now_iso()
        save_task(t)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                task_id = self._q.get(timeout=0.25)
            except queue.Empty:
                continue

            try:
                task = load_task(task_id)
            except Exception:
                continue

            if task.status == TaskStatus.canceled:
                continue

            handler = self._handlers.get(task.type)
            if not handler:
                task.status = TaskStatus.failed
                task.error = f"No handler for task type: {task.type.value}"
                task.stage = "failed"
                task.finished_at = utc_now_iso()
                save_task(task)
                continue

            task.status = TaskStatus.running
            task.started_at = utc_now_iso()
            task.stage = "running"
            task.progress = max(task.progress, 0.01)
            save_task(task)

            def update(stage: str, progress: float, message: str | None = None) -> None:
                try:
                    t = load_task(task_id)
                except Exception:
                    return
                if t.status == TaskStatus.canceled:
                    return
                t.stage = stage
                t.progress = float(max(0.0, min(1.0, progress)))
                if message is not None:
                    t.message = message
                save_task(t)

            def log(line: str) -> None:
                try:
                    t = load_task(task_id)
                except Exception:
                    return
                if t.status == TaskStatus.canceled:
                    return
                t.log.append(str(line))
                # cap logs to avoid unbounded growth
                if len(t.log) > 500:
                    t.log = t.log[-500:]
                save_task(t)

            try:
                result = handler(task_id, update, log)
                t2 = load_task(task_id)
                if t2.status == TaskStatus.canceled:
                    continue
                t2.status = TaskStatus.succeeded
                t2.stage = "done"
                t2.progress = 1.0
                t2.result = result
                t2.finished_at = utc_now_iso()
                save_task(t2)
            except Exception as exc:  # noqa: BLE001
                t2 = load_task(task_id)
                if t2.status == TaskStatus.canceled:
                    continue
                t2.status = TaskStatus.failed
                t2.stage = "failed"
                t2.error = str(exc)
                partial_result = getattr(exc, "partial_result", None)
                if partial_result is not None:
                    t2.result = partial_result
                t2.finished_at = utc_now_iso()
                save_task(t2)


task_manager = TaskManager()

