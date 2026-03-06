from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.settings import settings

DOI_STRATEGIES = {"extract_only", "title_crossref"}


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def storage_dir() -> Path:
    p = _backend_root() / settings.storage_dir
    p.mkdir(parents=True, exist_ok=True)
    return p


def uploads_dir() -> Path:
    p = storage_dir() / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def upload_dir(upload_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", upload_id)
    p = uploads_dir() / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def normalize_doi_strategy(value: str | None) -> str:
    s = str(value or "").strip().lower()
    if s in DOI_STRATEGIES:
        return s
    return "extract_only"


@dataclass
class UploadFileEntry:
    path: str
    size: int


@dataclass
class UploadManifest:
    upload_id: str
    mode: str  # "zip" | "folder"
    chunk_bytes: int
    total_bytes: int | None = None
    total_chunks: int | None = None
    filename: str | None = None
    files: list[UploadFileEntry] = field(default_factory=list)
    doi_strategy: str = "extract_only"  # extract_only | title_crossref
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["files"] = [asdict(f) for f in self.files]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UploadManifest":
        return cls(
            upload_id=str(d["upload_id"]),
            mode=str(d.get("mode") or "zip"),
            chunk_bytes=int(d.get("chunk_bytes") or 0),
            total_bytes=(int(d["total_bytes"]) if d.get("total_bytes") is not None else None),
            total_chunks=(int(d["total_chunks"]) if d.get("total_chunks") is not None else None),
            filename=d.get("filename"),
            files=[UploadFileEntry(path=str(x["path"]), size=int(x.get("size") or 0)) for x in (d.get("files") or [])],
            doi_strategy=normalize_doi_strategy(d.get("doi_strategy")),
            created_at=str(d.get("created_at") or utc_now_iso()),
        )


def manifest_path(upload_id: str) -> Path:
    return upload_dir(upload_id) / "manifest.json"


def scan_path(upload_id: str) -> Path:
    return upload_dir(upload_id) / "scan.json"


def overrides_path(upload_id: str) -> Path:
    return upload_dir(upload_id) / "overrides.json"


def doi_overrides_path(upload_id: str) -> Path:
    return upload_dir(upload_id) / "doi_overrides.json"


def paper_type_overrides_path(upload_id: str) -> Path:
    return upload_dir(upload_id) / "paper_type_overrides.json"


def save_manifest(m: UploadManifest) -> None:
    p = manifest_path(m.upload_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(m.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def load_manifest(upload_id: str) -> UploadManifest:
    p = manifest_path(upload_id)
    data = json.loads(p.read_text(encoding="utf-8"))
    return UploadManifest.from_dict(data)


def new_upload_id() -> str:
    return uuid.uuid4().hex[:12]


def safe_relpath(p: str) -> str:
    """
    Normalize a client-provided relative path, rejecting absolute paths and traversal.
    We store everything in POSIX-ish form using '/' separators.
    """
    s = (p or "").strip().replace("\\", "/")
    if not s or s.startswith("/") or re.match(r"^[A-Za-z]:/", s):
        raise ValueError(f"Invalid relative path: {p!r}")
    parts = [x for x in s.split("/") if x not in {"", "."}]
    if any(x == ".." for x in parts):
        raise ValueError(f"Invalid relative path (traversal): {p!r}")
    return "/".join(parts)


def zip_parts_dir(upload_id: str) -> Path:
    p = upload_dir(upload_id) / "parts" / "zip"
    p.mkdir(parents=True, exist_ok=True)
    return p


def file_parts_dir(upload_id: str, relpath: str) -> Path:
    safe = safe_relpath(relpath)
    p = upload_dir(upload_id) / "parts" / "files" / safe
    p.mkdir(parents=True, exist_ok=True)
    return p


def assembled_root(upload_id: str) -> Path:
    p = upload_dir(upload_id) / "files"
    p.mkdir(parents=True, exist_ok=True)
    return p


def extracted_root(upload_id: str) -> Path:
    p = upload_dir(upload_id) / "extracted"
    p.mkdir(parents=True, exist_ok=True)
    return p


def overrides_get(upload_id: str) -> dict[str, str]:
    # Back-compat: older versions stored DOI overrides in overrides.json.
    p = doi_overrides_path(upload_id)
    legacy = overrides_path(upload_id)
    if not p.exists() and legacy.exists():
        p = legacy
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        out[k] = v
    return out


def overrides_set(upload_id: str, key: str, doi: str) -> None:
    cur = overrides_get(upload_id)
    cur[str(key)] = str(doi)
    p = doi_overrides_path(upload_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def paper_type_overrides_get(upload_id: str) -> dict[str, str]:
    p = paper_type_overrides_path(upload_id)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        out[k] = v
    return out


def paper_type_overrides_set(upload_id: str, key: str, paper_type: str) -> None:
    cur = paper_type_overrides_get(upload_id)
    cur[str(key)] = str(paper_type)
    p = paper_type_overrides_path(upload_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
