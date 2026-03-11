from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class TaskType(str, Enum):
    ingest_path = "ingest_path"
    ingest_upload_ready = "ingest_upload_ready"
    upload_replace = "upload_replace"
    rebuild_paper = "rebuild_paper"
    rebuild_faiss = "rebuild_faiss"
    rebuild_all = "rebuild_all"
    rebuild_similarity = "rebuild_similarity"
    rebuild_fusion = "rebuild_fusion"
    rebuild_global_communities = "rebuild_global_communities"
    cleanup_legacy_propositions = "cleanup_legacy_propositions"
    update_similarity_paper = "update_similarity_paper"
    ingest_textbook = "ingest_textbook"
    discovery_batch = "discovery_batch"


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class TaskRecord:
    task_id: str
    type: TaskType
    status: TaskStatus
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    progress: float = 0.0
    stage: str = "queued"
    message: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskRecord":
        return cls(
            task_id=str(d["task_id"]),
            type=TaskType(str(d["type"])),
            status=TaskStatus(str(d["status"])),
            payload=dict(d.get("payload") or {}),
            created_at=str(d.get("created_at") or utc_now_iso()),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            progress=float(d.get("progress") or 0.0),
            stage=str(d.get("stage") or "queued"),
            message=d.get("message"),
            result=d.get("result"),
            error=d.get("error"),
            log=list(d.get("log") or []),
        )
