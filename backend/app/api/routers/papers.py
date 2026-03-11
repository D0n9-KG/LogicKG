from __future__ import annotations

import csv
import io
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.graph.neo4j_client import Neo4jClient
from app.settings import settings


router = APIRouter(prefix="/papers", tags=["papers"])


_SAFE_RELPATH = re.compile(r"^[A-Za-z0-9_.\-/]+$")


def _doi_sanitized(doi: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", doi.strip().lower())


def _canonical_dir_for_paper_id(paper_id: str) -> Path:
    if paper_id.startswith("doi:"):
        doi = paper_id[4:]
        p = Path(__file__).resolve().parents[3] / settings.storage_dir / "papers" / "doi" / _doi_sanitized(doi)
        if p.exists():
            return p
    # Fallback: resolve from Neo4j source_md_path
    return _source_dir_from_neo4j(paper_id)


def _source_md_file_for_paper_id(paper_id: str) -> Path | None:
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            paper = client.get_paper_basic(paper_id)
    except Exception:
        return None
    md_path = str(paper.get("source_md_path") or "").strip()
    if not md_path:
        return None
    p = Path(md_path)
    if not p.exists() or not p.is_file():
        return None
    return p


def _source_dir_from_neo4j(paper_id: str) -> Path:
    """Look up source_md_path in Neo4j and return its parent directory."""
    p = _source_md_file_for_paper_id(paper_id)
    if p is None:
        raise FileNotFoundError(f"Paper not found: {paper_id}")
    return p.parent


@router.get("/manage")
def list_papers_for_management(limit: int = Query(default=200, ge=1, le=2000), q: str | None = Query(default=None)):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {"papers": client.list_papers_for_management(limit=limit, query=q)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _safe_rel(rel: str) -> str:
    s = (rel or "").strip().replace("\\", "/")
    if not s or s.startswith("/") or ":" in s.split("/")[0]:
        raise ValueError("Invalid path")
    if not _SAFE_RELPATH.match(s):
        raise ValueError("Invalid path")
    parts = [p for p in s.split("/") if p not in {"", "."}]
    if any(p == ".." for p in parts):
        raise ValueError("Invalid path")
    return "/".join(parts)


# Images route first (more specific — has /images/ fixed segment)
@router.get("/{paper_id:path}/images/{rel_path:path}")
def get_paper_image(paper_id: str, rel_path: str):
    try:
        base = _canonical_dir_for_paper_id(paper_id)
        rel = _safe_rel(rel_path)
        p = (base / "images" / rel).resolve()
        root = (base / "images").resolve()
        p.relative_to(root)
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f"Image not found: {rel}")
        mt, _ = mimetypes.guess_type(str(p))
        return FileResponse(str(p), media_type=mt or "application/octet-stream")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{paper_id:path}/content")
def get_paper_content(paper_id: str):
    """Return the original markdown content for a paper."""
    try:
        base = _canonical_dir_for_paper_id(paper_id)
        md_file: Path | None = None
        exact_md = _source_md_file_for_paper_id(paper_id)
        if exact_md is not None and exact_md.exists() and exact_md.is_file():
            exact_md.resolve().relative_to(base.resolve())
            md_file = exact_md
        for name in ("source.md", "paper.md", "content.md"):
            if md_file is not None:
                break
            candidate = base / name
            if candidate.exists() and candidate.is_file():
                md_file = candidate
                break
        if md_file is None:
            raise FileNotFoundError(f"No markdown file found for {paper_id}")
        md_file.resolve().relative_to(base.resolve())
        text = md_file.read_text(encoding="utf-8", errors="replace")
        return PlainTextResponse(text, media_type="text/plain; charset=utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _bib_escape(value: str) -> str:
    """Escape special characters for BibTeX field values."""
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def _export_bibtex(detail: dict[str, Any]) -> str:
    """Generate BibTeX entry from paper detail."""
    paper = detail.get("paper") or {}
    doi = str(paper.get("doi") or "").strip()
    title = _bib_escape(str(paper.get("title") or "Untitled").strip())
    year = paper.get("year")
    authors = paper.get("authors")
    key = doi.replace("/", "_").replace(".", "_") if doi else "unknown"
    lines = [f"@article{{{key},"]
    lines.append(f"  title = {{{title}}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    if doi:
        lines.append(f"  doi = {{{_bib_escape(doi)}}},")
    if isinstance(authors, list) and authors:
        lines.append(f"  author = {{{_bib_escape(' and '.join(str(a) for a in authors))}}},")
    elif isinstance(authors, str) and authors.strip():
        lines.append(f"  author = {{{_bib_escape(authors.strip())}}},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _export_csv(detail: dict[str, Any]) -> str:
    """Generate CSV with claims from paper detail."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["claim_key", "text", "step_type", "confidence", "kinds"])
    for claim in detail.get("claims") or []:
        writer.writerow([
            str(claim.get("claim_key") or ""),
            str(claim.get("text") or ""),
            str(claim.get("step_type") or ""),
            str(claim.get("confidence") or ""),
            ";".join(str(k) for k in (claim.get("kinds") or [])),
        ])
    return buf.getvalue()


@router.get("/{paper_id:path}/export")
def export_paper(
    paper_id: str,
    format: str = Query(default="json", pattern="^(json|csv|bibtex)$"),
):
    """Export paper data in json, csv, or bibtex format."""
    try:
        with Neo4jClient(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password,
        ) as client:
            detail = client.get_paper_detail(paper_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if format == "bibtex":
        text = _export_bibtex(detail)
        return Response(
            content=text,
            media_type="application/x-bibtex; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=paper.bib"},
        )
    if format == "csv":
        text = _export_csv(detail)
        return Response(
            content=text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=claims.csv"},
        )
    # json (default)
    return Response(
        content=json.dumps(detail, ensure_ascii=False, default=str, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=paper.json"},
    )
