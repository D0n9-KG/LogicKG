from __future__ import annotations

import math
import os
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.ingest.pipeline import ingest_path
from app.ingest.scan_upload import scan_upload
from app.ingest.upload_actions import keep_existing, set_doi_override, set_paper_type_override
from app.ingest.upload_store import (
    UploadFileEntry,
    UploadManifest,
    assembled_root,
    extracted_root,
    file_parts_dir,
    load_manifest,
    new_upload_id,
    save_manifest,
    safe_relpath,
    zip_parts_dir,
)
from app.ingest.zip_utils import ZipSecurityError, safe_extract_zip
from app.tasks.manager import task_manager
from app.tasks.models import TaskType


router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestPathRequest(BaseModel):
    path: str


@router.post("/path")
def ingest_path_endpoint(req: IngestPathRequest):
    try:
        result = ingest_path(req.path)
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UploadStartRequest(BaseModel):
    mode: str = Field(pattern="^(zip|folder)$")
    chunk_bytes: int = Field(default=8 * 1024 * 1024, ge=256 * 1024, le=64 * 1024 * 1024)
    total_bytes: int | None = Field(default=None, ge=1)
    filename: str | None = None
    files: list[dict] | None = None  # folder mode: [{path,size}]
    doi_strategy: str = Field(default="extract_only", pattern="^(extract_only|title_crossref)$")


@router.post("/upload/start")
def upload_start(req: UploadStartRequest):
    try:
        upload_id = new_upload_id()
        files: list[UploadFileEntry] = []
        if req.mode == "folder":
            for f in req.files or []:
                p = safe_relpath(str(f.get("path") or ""))
                size = int(f.get("size") or 0)
                if size < 0:
                    continue
                files.append(UploadFileEntry(path=p, size=size))
        total_chunks = None
        if req.mode == "zip" and req.total_bytes is not None:
            total_chunks = int(math.ceil(req.total_bytes / req.chunk_bytes))
        m = UploadManifest(
            upload_id=upload_id,
            mode=req.mode,
            chunk_bytes=req.chunk_bytes,
            total_bytes=req.total_bytes,
            total_chunks=total_chunks,
            filename=req.filename,
            files=files,
            doi_strategy=req.doi_strategy,
        )
        save_manifest(m)
        return {"upload_id": upload_id, "chunk_bytes": req.chunk_bytes, "doi_strategy": req.doi_strategy}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/upload/status")
def upload_status(upload_id: str, file_path: str | None = None):
    try:
        m = load_manifest(upload_id)
        if m.mode == "zip":
            parts = zip_parts_dir(upload_id)
            idxs = []
            for p in parts.glob("*.part"):
                try:
                    idxs.append(int(p.stem))
                except ValueError:
                    continue
            idxs.sort()
            return {"mode": "zip", "received": idxs, "total_chunks": m.total_chunks}
        if not file_path:
            return {"mode": "folder", "files": len(m.files)}
        d = file_parts_dir(upload_id, file_path)
        idxs = []
        for p in d.glob("*.part"):
            try:
                idxs.append(int(p.stem))
            except ValueError:
                continue
        idxs.sort()
        return {"mode": "folder", "file_path": safe_relpath(file_path), "received": idxs}
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
        m = load_manifest(upload_id)
        if m.mode == "zip":
            parts = zip_parts_dir(upload_id)
            out = parts / f"{index}.part"
        else:
            if not file_path:
                raise HTTPException(status_code=400, detail="file_path is required for folder mode")
            d = file_parts_dir(upload_id, file_path)
            out = d / f"{index}.part"

        if out.exists() and out.stat().st_size > 0:
            # idempotent: already have this chunk
            return {"ok": True, "skipped": True}

        tmp = out.with_suffix(".part.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            while True:
                data = await blob.read(1024 * 1024)
                if not data:
                    break
                f.write(data)
        os.replace(tmp, out)
        return {"ok": True}
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _assemble_parts(parts_dir: Path, total_chunks: int, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "wb") as out:
        for i in range(total_chunks):
            p = parts_dir / f"{i}.part"
            if not p.exists():
                raise FileNotFoundError(f"Missing chunk {i} in {parts_dir}")
            with open(p, "rb") as src:
                while True:
                    buf = src.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
    os.replace(tmp, out_path)


@router.post("/upload/finish")
def upload_finish(upload_id: str):
    try:
        m = load_manifest(upload_id)
        if m.mode == "zip":
            if m.total_chunks is None:
                raise HTTPException(status_code=400, detail="total_bytes/total_chunks missing for zip mode")
            parts_dir = zip_parts_dir(upload_id)
            zip_path = Path(parts_dir).parents[1] / "payload.zip"
            _assemble_parts(parts_dir, m.total_chunks, zip_path)
            out_dir = extracted_root(upload_id)
            # Clear previous extracted contents
            if out_dir.exists():
                for p in sorted(out_dir.glob("**/*"), reverse=True):
                    if p.is_file():
                        p.unlink(missing_ok=True)
                    elif p.is_dir():
                        try:
                            p.rmdir()
                        except OSError:
                            pass
            try:
                safe_extract_zip(zip_path, out_dir)
            except ZipSecurityError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            root = assembled_root(upload_id)
            # Assemble each file
            for f in m.files:
                rel = safe_relpath(f.path)
                total_chunks = int(math.ceil(int(f.size) / m.chunk_bytes)) if f.size else 1
                parts_dir = file_parts_dir(upload_id, rel)
                out = root / rel
                _assemble_parts(parts_dir, total_chunks, out)

        scan = scan_upload(upload_id)
        return scan
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
        return scan_upload(upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UploadSetDoiRequest(BaseModel):
    upload_id: str
    unit_id: str
    doi: str


@router.post("/upload/set_doi")
def upload_set_doi(req: UploadSetDoiRequest):
    try:
        return set_doi_override(req.upload_id, req.unit_id, req.doi)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UploadSetPaperTypeRequest(BaseModel):
    upload_id: str
    unit_id: str
    paper_type: str = Field(pattern="^(research|review|software|theoretical|case_study)$")


@router.post("/upload/set_paper_type")
def upload_set_paper_type(req: UploadSetPaperTypeRequest):
    try:
        return set_paper_type_override(req.upload_id, req.unit_id, req.paper_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UploadUnitActionRequest(BaseModel):
    upload_id: str
    unit_id: str


@router.post("/upload/keep_existing")
def upload_keep_existing(req: UploadUnitActionRequest):
    try:
        return keep_existing(req.upload_id, req.unit_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/upload/commit_ready")
def upload_commit_ready(req: UploadUnitActionRequest):
    try:
        task_id = task_manager.submit(TaskType.ingest_upload_ready, {"upload_id": req.upload_id})
        return {"task_id": task_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/upload/replace_with_new")
def upload_replace_with_new(req: UploadUnitActionRequest):
    try:
        task_id = task_manager.submit(TaskType.upload_replace, {"upload_id": req.upload_id, "unit_id": req.unit_id})
        return {"task_id": task_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
