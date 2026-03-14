from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ingest.upload_store import safe_relpath
from app.settings import settings


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def storage_dir() -> Path:
    path = _backend_root() / settings.storage_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class TextbookUploadFileEntry:
    path: str
    size: int


@dataclass
class TextbookUploadManifest:
    upload_id: str
    mode: str  # zip | folder
    chunk_bytes: int
    total_bytes: int | None = None
    total_chunks: int | None = None
    filename: str | None = None
    files: list[TextbookUploadFileEntry] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["files"] = [asdict(entry) for entry in self.files]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TextbookUploadManifest":
        return cls(
            upload_id=str(data["upload_id"]),
            mode=str(data.get("mode") or "zip"),
            chunk_bytes=int(data.get("chunk_bytes") or 0),
            total_bytes=int(data["total_bytes"]) if data.get("total_bytes") is not None else None,
            total_chunks=int(data["total_chunks"]) if data.get("total_chunks") is not None else None,
            filename=str(data.get("filename")) if data.get("filename") is not None else None,
            files=[
                TextbookUploadFileEntry(path=str(item["path"]), size=int(item.get("size") or 0))
                for item in list(data.get("files") or [])
            ],
            created_at=str(data.get("created_at") or utc_now_iso()),
        )


def textbook_uploads_dir() -> Path:
    path = storage_dir() / "textbook_uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def textbook_upload_dir(upload_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", upload_id)
    path = textbook_uploads_dir() / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_textbook_upload_id() -> str:
    return uuid.uuid4().hex[:12]


def textbook_manifest_path(upload_id: str) -> Path:
    return textbook_upload_dir(upload_id) / "manifest.json"


def textbook_scan_path(upload_id: str) -> Path:
    return textbook_upload_dir(upload_id) / "scan.json"


def textbook_zip_parts_dir(upload_id: str) -> Path:
    path = textbook_upload_dir(upload_id) / "parts" / "zip"
    path.mkdir(parents=True, exist_ok=True)
    return path


def textbook_file_parts_dir(upload_id: str, rel_path: str) -> Path:
    path = textbook_upload_dir(upload_id) / "parts" / "files" / safe_relpath(rel_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def textbook_assembled_root(upload_id: str) -> Path:
    path = textbook_upload_dir(upload_id) / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def textbook_extracted_root(upload_id: str) -> Path:
    path = textbook_upload_dir(upload_id) / "extracted"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_textbook_manifest(manifest: TextbookUploadManifest) -> None:
    path = textbook_manifest_path(manifest.upload_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_textbook_manifest(upload_id: str) -> TextbookUploadManifest:
    path = textbook_manifest_path(upload_id)
    return TextbookUploadManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_textbook_scan(upload_id: str, payload: dict[str, Any]) -> None:
    path = textbook_scan_path(upload_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_textbook_scan(upload_id: str) -> dict[str, Any]:
    path = textbook_scan_path(upload_id)
    return json.loads(path.read_text(encoding="utf-8"))
