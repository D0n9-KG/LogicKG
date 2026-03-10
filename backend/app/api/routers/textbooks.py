"""Textbook REST API router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.graph.neo4j_client import Neo4jClient
from app.evolution.service import create_propositions_for_textbook
from app.settings import settings
from app.tasks.manager import task_manager
from app.tasks.models import TaskType


router = APIRouter(prefix="/textbooks", tags=["textbooks"])


# ── Request models ──

class IngestTextbookRequest(BaseModel):
    path: str = Field(min_length=1, description="Path to textbook .md file")
    title: str = Field(min_length=1, max_length=200)
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    edition: str | None = None
    doc_type: str = Field(default="textbook", description="textbook | standard | specification")


class FusionLinkRequest(BaseModel):
    textbook_id: str = Field(min_length=1)


# ── Endpoints ──

@router.post("/ingest")
def ingest_textbook(req: IngestTextbookRequest):
    """Submit a textbook ingestion task."""
    # Validate autoyoutu is configured
    from pathlib import Path
    autoyoutu_dir = settings.autoyoutu_dir.strip()
    if not autoyoutu_dir or not Path(autoyoutu_dir).is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"AUTOYOUTU_DIR not configured or not found: '{autoyoutu_dir}'. "
                   "Set AUTOYOUTU_DIR in .env to the autoyoutu project directory.",
        )
    if not Path(req.path).is_file():
        raise HTTPException(status_code=400, detail=f"Markdown file not found: {req.path}")
    try:
        task_id = task_manager.submit(TaskType.ingest_textbook, {
            "path": req.path,
            "metadata": {
                "title": req.title,
                "authors": req.authors,
                "year": req.year,
                "edition": req.edition,
                "doc_type": req.doc_type,
            },
        })
        return {"task_id": task_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("")
def list_textbooks(limit: int = 100):
    """List all textbooks with summary stats."""
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {"textbooks": client.list_textbooks(limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{textbook_id}")
def get_textbook(textbook_id: str):
    """Get textbook detail with chapter list."""
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return client.get_textbook_detail(textbook_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Textbook not found: {textbook_id}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{textbook_id}/chapters/{chapter_id}/entities")
def get_chapter_entities(textbook_id: str, chapter_id: str, limit: int = 500):
    """Get entities and relations for a chapter."""
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return client.get_chapter_entities(chapter_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{textbook_id}/chapters/{chapter_id}/graph")
def get_chapter_graph(textbook_id: str, chapter_id: str, entity_limit: int = 220, edge_limit: int = 420):
    """Get a chapter graph snapshot with entities, relations, and communities."""
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return client.get_chapter_graph_snapshot(chapter_id, entity_limit=entity_limit, edge_limit=edge_limit)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Chapter not found: {chapter_id}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{textbook_id}/graph")
def get_textbook_graph(textbook_id: str, entity_limit: int = 260, edge_limit: int = 520):
    """Get a textbook graph snapshot with chapters, entities, relations, and communities."""
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return client.get_textbook_graph_snapshot(textbook_id, entity_limit=entity_limit, edge_limit=edge_limit)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Textbook not found: {textbook_id}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{textbook_id}/entities")
def get_textbook_entities(textbook_id: str, limit: int = 2000):
    """Get all entities across the textbook."""
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {"entities": client.get_textbook_entities(textbook_id, limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{textbook_id}")
def delete_textbook(textbook_id: str):
    """Delete a textbook and all its chapters/entities."""
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            result = client.delete_textbook(textbook_id)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/fusion/link")
def fusion_link(req: FusionLinkRequest):
    """Create Propositions for textbook entities and link to evolution layer."""
    try:
        stats = create_propositions_for_textbook(req.textbook_id)
        return {"ok": True, **stats}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
