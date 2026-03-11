from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.tasks.manager import task_manager
from app.tasks.models import TaskType
from app.tasks.store import list_tasks, load_task


router = APIRouter(prefix="/tasks", tags=["tasks"])


class SubmitTaskResponse(BaseModel):
    task_id: str


class RebuildCommunityTaskRequest(BaseModel):
    textbook_id: str | None = None


class IngestPathTaskRequest(BaseModel):
    path: str = Field(min_length=1)


class DeletePapersTaskRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list, min_length=1)
    trigger_rebuild: bool = True


class DeleteTextbooksTaskRequest(BaseModel):
    textbook_ids: list[str] = Field(default_factory=list, min_length=1)
    trigger_rebuild: bool = True


@router.post("/ingest/path", response_model=SubmitTaskResponse)
def submit_ingest_path(req: IngestPathTaskRequest):
    try:
        task_id = task_manager.submit(TaskType.ingest_path, {"path": req.path})
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class RebuildPaperTaskRequest(BaseModel):
    paper_id: str = Field(min_length=3)
    rebuild_faiss: bool = True


@router.post("/rebuild/paper", response_model=SubmitTaskResponse)
def submit_rebuild_paper(req: RebuildPaperTaskRequest):
    try:
        task_id = task_manager.submit(
            TaskType.rebuild_paper,
            {"paper_id": req.paper_id, "rebuild_faiss": bool(req.rebuild_faiss)},
        )
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/rebuild/faiss", response_model=SubmitTaskResponse)
def submit_rebuild_faiss():
    try:
        task_id = task_manager.submit(TaskType.rebuild_faiss, {})
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/rebuild/all", response_model=SubmitTaskResponse)
def submit_rebuild_all():
    try:
        task_id = task_manager.submit(TaskType.rebuild_all, {})
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/rebuild/similarity", response_model=SubmitTaskResponse)
def submit_rebuild_similarity():
    try:
        task_id = task_manager.submit(TaskType.rebuild_similarity, {})
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/delete/papers", response_model=SubmitTaskResponse)
def submit_delete_papers(req: DeletePapersTaskRequest):
    try:
        task_id = task_manager.submit(
            TaskType.delete_papers_batch,
            {
                "paper_ids": req.paper_ids,
                "trigger_rebuild": bool(req.trigger_rebuild),
            },
        )
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/delete/textbooks", response_model=SubmitTaskResponse)
def submit_delete_textbooks(req: DeleteTextbooksTaskRequest):
    try:
        task_id = task_manager.submit(
            TaskType.delete_textbooks_batch,
            {
                "textbook_ids": req.textbook_ids,
                "trigger_rebuild": bool(req.trigger_rebuild),
            },
        )
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/rebuild/fusion", response_model=SubmitTaskResponse)
def submit_rebuild_fusion():
    try:
        task_id = task_manager.submit(TaskType.rebuild_fusion, {})
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/rebuild/community", response_model=SubmitTaskResponse)
def submit_rebuild_community(req: RebuildCommunityTaskRequest):
    try:
        payload = {}
        textbook_id = str(req.textbook_id or "").strip()
        if textbook_id:
            payload["textbook_id"] = textbook_id
        task_id = task_manager.submit(TaskType.rebuild_global_communities, payload)
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cleanup/propositions", response_model=SubmitTaskResponse)
def submit_cleanup_legacy_propositions():
    try:
        task_id = task_manager.submit(TaskType.cleanup_legacy_propositions, {})
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UpdateSimilarityPaperRequest(BaseModel):
    paper_id: str = Field(min_length=3)


@router.post("/similarity/paper", response_model=SubmitTaskResponse)
def submit_update_similarity_paper(req: UpdateSimilarityPaperRequest):
    try:
        task_id = task_manager.submit(TaskType.update_similarity_paper, {"paper_id": req.paper_id})
        return SubmitTaskResponse(task_id=task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("")
def tasks_list(limit: int = 80, keep_finished: int = 10, prune_finished: bool = True):
    try:
        return {"tasks": [t.to_dict() for t in list_tasks(limit=limit, keep_finished=keep_finished, prune_finished=prune_finished)]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{task_id}")
def get_task(task_id: str):
    try:
        return load_task(task_id).to_dict()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str):
    ok = task_manager.cancel(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Task not cancelable or not found")
    return {"ok": True}
