from __future__ import annotations

import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

from app.graph.neo4j_client import paper_id_for_md_path
from app.ingest.pipeline import ingest_markdowns
from app.ingest.rebuild import replace_paper_from_md_path
from app.ingest.scan_upload import scan_upload
from app.schema_store import normalize_paper_type, _PAPER_TYPE_SET
from app.ingest.upload_store import (
    assembled_root,
    extracted_root,
    load_manifest,
    overrides_set,
    paper_type_overrides_set,
    safe_relpath,
    storage_dir,
)


ProgressFn = Callable[[str, float, str | None], None]
LogFn = Callable[[str], None]

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def staging_root(upload_id: str) -> Path:
    m = load_manifest(upload_id)
    return extracted_root(upload_id) if m.mode == "zip" else assembled_root(upload_id)


def _doi_sanitized(doi: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", doi.strip().lower())


def canonical_dir_for_doi(doi: str) -> Path:
    p = storage_dir() / "papers" / "doi" / _doi_sanitized(doi)
    p.mkdir(parents=True, exist_ok=True)
    return p


_IMG_MD_RE = re.compile(r"!\[[^\]]*\]\((?P<path>[^)]+)\)")
_DOI_LINE_RE = re.compile(r"\bDOI:\s*(?P<doi>10\.\d{4,9}/[^\s]+)", re.IGNORECASE)


def _extract_md_image_paths(md_path: Path) -> set[str]:
    raw = md_path.read_text(encoding="utf-8", errors="ignore")
    out: set[str] = set()
    for m in _IMG_MD_RE.finditer(raw):
        p = (m.group("path") or "").strip().strip("\"'").replace("\\", "/")
        if not p or p.startswith("http://") or p.startswith("https://"):
            continue
        # strip optional title after whitespace: (path "title")
        if " " in p:
            p = p.split(" ", 1)[0].strip()
        if not p:
            continue
        parts = [x for x in p.split("/") if x not in {"", "."}]
        if any(x == ".." for x in parts):
            continue
        out.add("/".join(parts))
    return out


def copy_unit_to_canonical(upload_id: str, unit: dict[str, Any], replace: bool = False) -> Path:
    """
    Copy the unit's md and referenced images into backend/storage/papers/doi/<doi>/, preserving relative paths.
    Returns the canonical md path.
    """
    doi = str(unit.get("doi") or "").strip().lower()
    if not doi or not _DOI_RE.match(doi):
        raise ValueError("Missing/invalid DOI for unit")

    root = staging_root(upload_id)
    md_rel = safe_relpath(str(unit.get("md_rel_path") or ""))
    md_src = root / md_rel
    if not md_src.exists():
        raise FileNotFoundError(f"Staged markdown not found: {md_rel}")

    can_dir = canonical_dir_for_doi(doi)
    if replace and can_dir.exists():
        shutil.rmtree(can_dir, ignore_errors=True)
        can_dir.mkdir(parents=True, exist_ok=True)

    can_md = can_dir / "source.md"
    raw = md_src.read_text(encoding="utf-8", errors="ignore")
    m_doi = _DOI_LINE_RE.search(raw)
    existing = m_doi.group("doi").strip().lower() if m_doi else None
    if existing != doi:
        if m_doi:
            raw = _DOI_LINE_RE.sub(f"DOI: {doi}", raw, count=1)
        else:
            raw = f"DOI: {doi}\n\n" + raw
    can_md.write_text(raw, encoding="utf-8")

    # Write canonical meta.json (used to preserve paper_type and provenance across rebuilds).
    paper_type = normalize_paper_type(unit.get("paper_type"))
    meta = {
        "doi": doi,
        "paper_type": paper_type,
        "source_upload_id": upload_id,
    }
    (can_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Copy only referenced images (must be under images/)
    md_dir = md_src.parent
    img_paths = _extract_md_image_paths(md_src)
    for rel in sorted(img_paths):
        if not rel.startswith("images/"):
            continue
        src = md_dir / rel
        if not src.exists() or not src.is_file():
            continue
        dst = can_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    return can_md


def _delete_staged_unit(upload_id: str, unit: dict[str, Any]) -> None:
    root = staging_root(upload_id)
    unit_dir = safe_relpath(str(unit.get("unit_rel_dir") or ""))
    p = root / unit_dir
    if not p.exists():
        return
    # Safety: ensure p is within root
    try:
        p.resolve().relative_to(root.resolve())
    except Exception:
        raise RuntimeError("Refuse to delete path outside staging root")
    shutil.rmtree(p, ignore_errors=True)


def set_doi_override(upload_id: str, unit_id: str, doi: str) -> dict[str, Any]:
    d = doi.strip().lower()
    if not _DOI_RE.match(d):
        raise ValueError(f"Invalid DOI: {doi!r}")
    overrides_set(upload_id, unit_id, d)
    return scan_upload(upload_id)


def set_paper_type_override(upload_id: str, unit_id: str, paper_type: str) -> dict[str, Any]:
    pt = str(paper_type or "").strip().lower()
    if pt not in _PAPER_TYPE_SET:
        raise ValueError(f"Invalid paper_type: {paper_type!r}")
    paper_type_overrides_set(upload_id, unit_id, pt)
    return scan_upload(upload_id)


def commit_ready(upload_id: str, progress: ProgressFn | None = None, log: LogFn | None = None) -> dict[str, Any]:
    def notify(stage: str, p: float, msg: str | None = None) -> None:
        if progress:
            progress(stage, p, msg)

    def write_log(line: str) -> None:
        if log:
            log(line)

    scan = scan_upload(upload_id)
    units: list[dict[str, Any]] = list(scan.get("units") or [])
    ready = [u for u in units if u.get("status") == "ready" and u.get("doi")]
    if not ready:
        return {"ok": True, "ingested": 0, "message": "No ready units"}

    notify("upload:copy", 0.05, f"Copying {len(ready)} paper(s) to canonical storage")
    md_files: list[str] = []
    for idx, u in enumerate(ready, start=1):
        can_md = copy_unit_to_canonical(upload_id, u, replace=False)
        md_files.append(str(can_md))
        write_log(f"copied {u.get('doi')} -> {can_md}")
        notify("upload:copy", 0.05 + 0.25 * (idx / max(1, len(ready))), None)

    notify("upload:ingest", 0.35, "Ingesting into Neo4j / building artifacts")
    res = ingest_markdowns(md_files, progress=progress)

    notify("upload:cleanup", 0.95, "Cleaning up staged units")
    for u in ready:
        _delete_staged_unit(upload_id, u)

    notify("upload:done", 1.0, "Done")
    return {"ok": True, "ingested": len(ready), "result": res}


def keep_existing(upload_id: str, unit_id: str) -> dict[str, Any]:
    scan = scan_upload(upload_id)
    units: list[dict[str, Any]] = list(scan.get("units") or [])
    u = next((x for x in units if str(x.get("unit_id")) == unit_id), None)
    if not u:
        raise FileNotFoundError(f"Unit not found: {unit_id}")
    _delete_staged_unit(upload_id, u)
    return scan_upload(upload_id)


def replace_with_new(upload_id: str, unit_id: str, progress: ProgressFn | None = None, log: LogFn | None = None) -> dict[str, Any]:
    def notify(stage: str, p: float, msg: str | None = None) -> None:
        if progress:
            progress(stage, p, msg)

    scan = scan_upload(upload_id)
    units: list[dict[str, Any]] = list(scan.get("units") or [])
    u = next((x for x in units if str(x.get("unit_id")) == unit_id), None)
    if not u:
        raise FileNotFoundError(f"Unit not found: {unit_id}")
    doi = str(u.get("doi") or "").strip().lower()
    if not doi:
        raise ValueError("Unit has no DOI")
    paper_id = f"doi:{doi}"

    notify("upload:copy_replace", 0.10, "Copying new version to canonical storage")
    can_md = copy_unit_to_canonical(upload_id, u, replace=True)
    notify("upload:replace", 0.35, "Replacing paper subgraph in Neo4j")
    replace_paper_from_md_path(paper_id, str(can_md), progress=progress, log=log)
    _delete_staged_unit(upload_id, u)
    notify("upload:done", 1.0, "Done")
    return {"ok": True, "paper_id": paper_id, "source_md_path": str(can_md)}
