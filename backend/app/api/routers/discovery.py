from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.discovery.feedback_service import apply_feedback
from app.ops_config_store import merge_discovery_config
from app.tasks.manager import task_manager
from app.tasks.models import TaskStatus, TaskType
from app.tasks.store import list_tasks


router = APIRouter(prefix="/discovery", tags=["discovery"])


class DiscoveryBatchRequest(BaseModel):
    domain: str | None = Field(default=None, min_length=1)
    dry_run: bool | None = None
    max_gaps: int | None = Field(default=None, ge=1, le=64)
    candidates_per_gap: int | None = Field(default=None, ge=1, le=3)
    use_llm: bool | None = None
    hop_order: int | None = Field(default=None, ge=1, le=3)
    adjacent_samples: int | None = Field(default=None, ge=0, le=30)
    random_samples: int | None = Field(default=None, ge=0, le=30)
    rag_top_k: int | None = Field(default=None, ge=1, le=8)
    prompt_optimize: bool | None = None
    community_method: str | None = Field(default=None, min_length=1)
    community_samples: int | None = Field(default=None, ge=0, le=30)
    prompt_optimization_method: str | None = Field(default=None, min_length=1)


class DiscoveryFeedbackRequest(BaseModel):
    candidate_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    note: str | None = None


def _latest_discovery_candidates() -> tuple[list[dict], str | None]:
    tasks = list_tasks(limit=300, keep_finished=100, prune_finished=False)
    for t in tasks:
        if t.type != TaskType.discovery_batch:
            continue
        if t.status != TaskStatus.succeeded:
            continue
        result = t.result or {}
        candidates = result.get("candidates")
        if isinstance(candidates, list):
            return [dict(c) for c in candidates if isinstance(c, dict)], t.task_id
    return [], None


@router.post("/batch")
def submit_discovery_batch(req: DiscoveryBatchRequest):
    try:
        effective = merge_discovery_config(req.model_dump(exclude_none=True))
        task_id = task_manager.submit(
            TaskType.discovery_batch,
            {
                "domain": effective["domain"],
                "dry_run": effective["dry_run"],
                "max_gaps": effective["max_gaps"],
                "candidates_per_gap": effective["candidates_per_gap"],
                "use_llm": effective["use_llm"],
                "hop_order": effective["hop_order"],
                "adjacent_samples": effective["adjacent_samples"],
                "random_samples": effective["random_samples"],
                "rag_top_k": effective["rag_top_k"],
                "prompt_optimize": effective["prompt_optimize"],
                "community_method": effective["community_method"],
                "community_samples": effective["community_samples"],
                "prompt_optimization_method": effective["prompt_optimization_method"],
            },
        )
        return {"ok": True, "task_id": task_id, "status": "queued"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/candidates")
def list_discovery_candidates():
    candidates, source_task_id = _latest_discovery_candidates()
    return {"candidates": candidates, "source_task_id": source_task_id}


@router.get("/candidates/{candidate_id}")
def get_discovery_candidate(candidate_id: str):
    candidates, source_task_id = _latest_discovery_candidates()
    target = str(candidate_id or "").strip()
    for item in candidates:
        if str(item.get("candidate_id") or "").strip() == target:
            return {"candidate": item, "source_task_id": source_task_id}
    raise HTTPException(status_code=404, detail=f"Discovery candidate not found: {candidate_id}")


@router.post("/feedback")
def submit_discovery_feedback(req: DiscoveryFeedbackRequest):
    try:
        return apply_feedback(candidate_id=req.candidate_id, label=req.label, note=req.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
