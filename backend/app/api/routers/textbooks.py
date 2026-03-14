"""Textbook REST API router."""

from __future__ import annotations

import math
import os
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.delete_assets import delete_textbook_asset
from app.graph.neo4j_client import Neo4jClient
from app.ingest.scan_textbook_upload import scan_textbook_upload
from app.ingest.textbook_upload_actions import skip_textbook_unit
from app.ingest.textbook_upload_store import (
    TextbookUploadFileEntry,
    TextbookUploadManifest,
    load_textbook_manifest,
    new_textbook_upload_id,
    save_textbook_manifest,
    textbook_assembled_root,
    textbook_extracted_root,
    textbook_file_parts_dir,
    textbook_zip_parts_dir,
)
from app.ingest.upload_store import safe_relpath
from app.ingest.zip_utils import ZipSecurityError, safe_extract_zip
from app.settings import settings
from app.tasks.manager import task_manager
from app.tasks.models import TaskType


router = APIRouter(prefix="/textbooks", tags=["textbooks"])


class IngestTextbookRequest(BaseModel):
    path: str = Field(min_length=1, description="Path to textbook .md file")
    title: str = Field(min_length=1, max_length=200)
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    edition: str | None = None
    doc_type: str = Field(default="textbook", description="textbook | standard | specification")


class FusionLinkRequest(BaseModel):
    textbook_id: str = Field(min_length=1)


class TextbookUploadStartRequest(BaseModel):
    mode: str = Field(pattern="^(zip|folder)$")
    chunk_bytes: int = Field(default=8 * 1024 * 1024, ge=256 * 1024, le=64 * 1024 * 1024)
    total_bytes: int | None = Field(default=None, ge=1)
    filename: str | None = None
    files: list[dict] | None = None


class TextbookUploadUnitActionRequest(BaseModel):
    upload_id: str
    unit_id: str


class TextbookUploadCommitRequest(BaseModel):
    upload_id: str


def _assemble_parts(parts_dir: Path, total_chunks: int, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "wb") as out:
        for index in range(total_chunks):
            part_path = parts_dir / f"{index}.part"
            if not part_path.exists():
                raise FileNotFoundError(f"Missing chunk {index} in {parts_dir}")
            with open(part_path, "rb") as src:
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
    os.replace(tmp, out_path)


def _clear_directory(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.glob("**/*"), reverse=True):
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


@router.post("/ingest")
def ingest_textbook(req: IngestTextbookRequest):
    """Submit a textbook ingestion task."""
    autoyoutu_dir = settings.autoyoutu_dir.strip()
    if not autoyoutu_dir or not Path(autoyoutu_dir).is_dir():
        raise HTTPException(
            status_code=400,
            detail=(
                f"AUTOYOUTU_DIR not configured or not found: '{autoyoutu_dir}'. "
                "Set AUTOYOUTU_DIR in .env to the autoyoutu project directory."
            ),
        )
    if not Path(req.path).is_file():
        raise HTTPException(status_code=400, detail=f"Markdown file not found: {req.path}")
    try:
        task_id = task_manager.submit(
            TaskType.ingest_textbook,
            {
                "path": req.path,
                "metadata": {
                    "title": req.title,
                    "authors": req.authors,
                    "year": req.year,
                    "edition": req.edition,
                    "doc_type": req.doc_type,
                },
            },
        )
        return {"task_id": task_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/upload/start")
def upload_start(req: TextbookUploadStartRequest):
    try:
        upload_id = new_textbook_upload_id()
        files: list[TextbookUploadFileEntry] = []
        if req.mode == "folder":
            for file_info in req.files or []:
                rel_path = safe_relpath(str(file_info.get("path") or ""))
                size = int(file_info.get("size") or 0)
                if size < 0:
                    continue
                files.append(TextbookUploadFileEntry(path=rel_path, size=size))
        total_chunks = None
        if req.mode == "zip" and req.total_bytes is not None:
            total_chunks = int(math.ceil(req.total_bytes / req.chunk_bytes))
        manifest = TextbookUploadManifest(
            upload_id=upload_id,
            mode=req.mode,
            chunk_bytes=req.chunk_bytes,
            total_bytes=req.total_bytes,
            total_chunks=total_chunks,
            filename=req.filename,
            files=files,
        )
        save_textbook_manifest(manifest)
        return {"upload_id": upload_id, "chunk_bytes": req.chunk_bytes}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/upload/status")
def upload_status(upload_id: str, file_path: str | None = None):
    try:
        manifest = load_textbook_manifest(upload_id)
        if manifest.mode == "zip":
            parts = textbook_zip_parts_dir(upload_id)
            received = []
            for path in parts.glob("*.part"):
                try:
                    received.append(int(path.stem))
                except ValueError:
                    continue
            received.sort()
            return {"mode": "zip", "received": received, "total_chunks": manifest.total_chunks}
        if not file_path:
            return {"mode": "folder", "files": len(manifest.files)}
        parts_dir = textbook_file_parts_dir(upload_id, file_path)
        received = []
        for path in parts_dir.glob("*.part"):
            try:
                received.append(int(path.stem))
            except ValueError:
                continue
        received.sort()
        return {"mode": "folder", "file_path": safe_relpath(file_path), "received": received}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    index: int = Form(..., ge=0),
    file_path: str | None = Form(None),
    blob: UploadFile = File(...),
):
    try:
        manifest = load_textbook_manifest(upload_id)
        if manifest.mode == "zip":
            out_path = textbook_zip_parts_dir(upload_id) / f"{index}.part"
        else:
            if not file_path:
                raise HTTPException(status_code=400, detail="file_path is required for folder mode")
            out_path = textbook_file_parts_dir(upload_id, file_path) / f"{index}.part"
        if out_path.exists() and out_path.stat().st_size > 0:
            return {"ok": True, "skipped": True}
        tmp = out_path.with_suffix(".part.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as out:
            while True:
                data = await blob.read(1024 * 1024)
                if not data:
                    break
                out.write(data)
        os.replace(tmp, out_path)
        return {"ok": True}
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/upload/finish")
def upload_finish(upload_id: str):
    try:
        manifest = load_textbook_manifest(upload_id)
        if manifest.mode == "zip":
            if manifest.total_chunks is None:
                raise HTTPException(status_code=400, detail="total_bytes/total_chunks missing for zip mode")
            parts_dir = textbook_zip_parts_dir(upload_id)
            zip_path = parts_dir.parents[1] / "payload.zip"
            _assemble_parts(parts_dir, manifest.total_chunks, zip_path)
            out_dir = textbook_extracted_root(upload_id)
            _clear_directory(out_dir)
            try:
                safe_extract_zip(zip_path, out_dir)
            except ZipSecurityError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            root = textbook_assembled_root(upload_id)
            for file_info in manifest.files:
                rel_path = safe_relpath(file_info.path)
                total_chunks = int(math.ceil(int(file_info.size) / manifest.chunk_bytes)) if file_info.size else 1
                parts_dir = textbook_file_parts_dir(upload_id, rel_path)
                _assemble_parts(parts_dir, total_chunks, root / rel_path)
        return scan_textbook_upload(upload_id)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/upload/scan")
def upload_scan(upload_id: str):
    try:
        return scan_textbook_upload(upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/upload/skip")
def upload_skip(req: TextbookUploadUnitActionRequest):
    try:
        return skip_textbook_unit(req.upload_id, req.unit_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/upload/commit_ready")
def upload_commit_ready(req: TextbookUploadCommitRequest):
    try:
        task_id = task_manager.submit(TaskType.ingest_textbook_upload_ready, {"upload_id": req.upload_id})
        return {"task_id": task_id, "task_type": TaskType.ingest_textbook_upload_ready.value}
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
        return delete_textbook_asset(textbook_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Textbook not found: {textbook_id}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/fusion/link")
def fusion_link(req: FusionLinkRequest):
    """Submit a global community rebuild task after textbook import/update."""
    try:
        task_id = task_manager.submit(TaskType.rebuild_global_communities, {"textbook_id": req.textbook_id})
        return {"task_id": task_id, "task_type": TaskType.rebuild_global_communities.value}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
