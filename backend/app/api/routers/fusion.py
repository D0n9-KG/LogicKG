from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.fusion.service import (
    get_fusion_graph,
    list_fusion_basics_for_section,
    list_fusion_sections_for_paper,
    retrieve_fusion_basics,
)
from app.tasks.manager import task_manager
from app.tasks.models import TaskType


router = APIRouter(prefix="/fusion", tags=["fusion"])


class FusionRebuildRequest(BaseModel):
    paper_id: str | None = None


class FusionRetrieveRequest(BaseModel):
    question: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    step_type: str | None = None
    k: int = Field(default=8, ge=1, le=20)


@router.post("/rebuild")
def rebuild_fusion(req: FusionRebuildRequest):
    try:
        task_id = task_manager.submit(
            TaskType.rebuild_fusion,
            {"paper_id": req.paper_id},
        )
        return {"task_id": task_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/graph")
def fusion_graph(limit_nodes: int = 1000, limit_edges: int = 3000):
    try:
        return get_fusion_graph(limit_nodes=limit_nodes, limit_edges=limit_edges)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/paper/{paper_id}/sections")
def fusion_sections(paper_id: str):
    try:
        return list_fusion_sections_for_paper(paper_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/sections")
def fusion_sections_query(paper_id: str):
    try:
        return list_fusion_sections_for_paper(paper_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/paper/{paper_id}/section/{step_type}/basics")
def fusion_section_basics(paper_id: str, step_type: str, limit: int = 50):
    try:
        return list_fusion_basics_for_section(paper_id, step_type, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/basics")
def fusion_section_basics_query(paper_id: str, step_type: str, limit: int = 50):
    try:
        return list_fusion_basics_for_section(paper_id, step_type, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/retrieve")
def fusion_retrieve(req: FusionRetrieveRequest):
    try:
        return retrieve_fusion_basics(
            question=req.question,
            paper_id=req.paper_id,
            step_type=req.step_type,
            k=req.k,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
