from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.graph.neo4j_client import Neo4jClient
from app.settings import settings


router = APIRouter(prefix="/collections", tags=["collections"])


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class CreateCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class RenameCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.get("")
def list_collections(limit: int = 200):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.ensure_schema()
            return {"collections": client.list_collections(limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("")
def create_collection(req: CreateCollectionRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    collection_id = f"col-{uuid.uuid4().hex[:12]}"
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.ensure_schema()
            client.create_collection(collection_id=collection_id, name=name, created_at=_utc_now_iso())
        return {"ok": True, "collection_id": collection_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/{collection_id}")
def rename_collection(collection_id: str, req: RenameCollectionRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.ensure_schema()
            client.rename_collection(collection_id=collection_id, name=name, updated_at=_utc_now_iso())
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{collection_id}")
def delete_collection(collection_id: str):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.ensure_schema()
            client.delete_collection(collection_id=collection_id)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{collection_id}/papers/{paper_id:path}")
def add_paper(collection_id: str, paper_id: str):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.ensure_schema()
            client.add_paper_to_collection(collection_id=collection_id, paper_id=paper_id)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{collection_id}/papers/{paper_id:path}")
def remove_paper(collection_id: str, paper_id: str):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.ensure_schema()
            client.remove_paper_from_collection(collection_id=collection_id, paper_id=paper_id)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

