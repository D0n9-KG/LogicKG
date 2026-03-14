from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.crossref.client import CrossrefClient
from app.graph.neo4j_client import Neo4jClient
from app.ingest.parse_md import parse_mineru_markdown
from app.schema_store import normalize_paper_type
from app.ingest.upload_store import (
    assembled_root,
    extracted_root,
    load_manifest,
    normalize_doi_strategy,
    overrides_get,
    paper_type_overrides_get,
    safe_relpath,
    scan_path,
    upload_dir,
)
from app.settings import settings


_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_CROSSREF_CONFIDENCE_THRESHOLD = 0.25


def _crossref_workers(crossref: CrossrefClient | None, item_count: int) -> int:
    if crossref is None:
        return 1
    try:
        workers = int(crossref.recommended_workers())
    except Exception:  # noqa: BLE001
        workers = 1
    return max(1, min(workers, max(1, int(item_count))))


@dataclass
class PaperUnit:
    unit_id: str
    unit_rel_dir: str
    md_rel_path: str
    doi: str | None
    title: str | None
    year: int | None
    paper_type: str  # research | review
    status: str  # ready | conflict | need_doi | error
    error: str | None = None
    existing_paper_id: str | None = None


def scan_upload(upload_id: str) -> dict[str, Any]:
    m = load_manifest(upload_id)
    if m.mode == "zip":
        root = extracted_root(upload_id)
    else:
        root = assembled_root(upload_id)

    doi_strategy = normalize_doi_strategy(getattr(m, "doi_strategy", None))
    overrides = overrides_get(upload_id)
    paper_type_overrides = paper_type_overrides_get(upload_id)
    crossref: CrossrefClient | None = CrossrefClient() if doi_strategy == "title_crossref" else None

    units: list[PaperUnit] = []
    errors: list[dict[str, Any]] = []
    pending_crossref: list[tuple[int, str, str]] = []

    # Detect candidate paper folders: directory containing exactly one *.md and an images/ sibling folder
    for d in sorted({p.parent for p in root.rglob("*.md")}):
        try:
            rel_dir = d.relative_to(root).as_posix()
        except Exception:
            continue
        images_dir = d / "images"
        if not images_dir.exists() or not images_dir.is_dir():
            continue
        md_files = list(d.glob("*.md"))
        if len(md_files) != 1:
            errors.append({"unit_dir": rel_dir, "error": f"Expected 1 md file, found {len(md_files)}"})
            continue
        md_path = md_files[0]
        md_rel = md_path.relative_to(root).as_posix()

        unit_id = safe_relpath(md_rel)
        doi_override = overrides.get(unit_id)
        paper_type = normalize_paper_type(paper_type_overrides.get(unit_id))
        try:
            doc = parse_mineru_markdown(str(md_path))
        except Exception as exc:  # noqa: BLE001
            units.append(
                PaperUnit(
                    unit_id=unit_id,
                    unit_rel_dir=rel_dir,
                    md_rel_path=md_rel,
                    doi=None,
                    title=None,
                    year=None,
                    paper_type=paper_type,
                    status="error",
                    error=str(exc),
                )
            )
            continue

        doi = (doi_override or doc.paper.doi or "").strip().lower() or None
        if not doi and crossref:
            query = (doc.paper.title or doc.paper.title_alt or "").strip()
            if query:
                pending_crossref.append((len(units), rel_dir, query))
        if doi and not _DOI_RE.match(doi):
            doi = None

        units.append(
            PaperUnit(
                unit_id=unit_id,
                unit_rel_dir=rel_dir,
                md_rel_path=md_rel,
                doi=doi,
                title=doc.paper.title or doc.paper.title_alt,
                year=doc.paper.year,
                paper_type=paper_type,
                status="need_doi" if not doi else "ready",
            )
        )

    def _resolve_title_doi(index: int, rel_dir: str, query: str) -> tuple[int, str, str | None]:
        try:
            r = crossref.resolve_reference(query) if crossref else None
            selected = r.selected if r else None
            doi = None
            if selected and selected.doi and float(r.confidence) >= _CROSSREF_CONFIDENCE_THRESHOLD:
                doi = str(selected.doi).strip().lower()
            return index, rel_dir, doi
        except Exception as exc:  # noqa: BLE001
            errors.append({"unit_dir": rel_dir, "error": f"Crossref title DOI resolve failed: {exc}"})
            return index, rel_dir, None

    workers = _crossref_workers(crossref, len(pending_crossref))
    if pending_crossref and workers == 1:
        resolved = [_resolve_title_doi(index, rel_dir, query) for index, rel_dir, query in pending_crossref]
    elif pending_crossref:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_resolve_title_doi, index, rel_dir, query) for index, rel_dir, query in pending_crossref]
            resolved = [future.result() for future in futures]
    else:
        resolved = []

    for index, _rel_dir, doi in resolved:
        if not doi or not _DOI_RE.match(doi):
            continue
        units[index].doi = doi
        if units[index].status == "need_doi":
            units[index].status = "ready"

    # Determine conflicts against Neo4j (best effort)
    if any(u.status == "ready" and u.doi for u in units):
        try:
            with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
                for u in units:
                    if u.status != "ready" or not u.doi:
                        continue
                    paper_id = f"doi:{u.doi}"
                    try:
                        p = client.get_paper_basic(paper_id)
                        u.existing_paper_id = paper_id
                        # Only treat as conflict if the paper is already fully ingested.
                        # If a stub Paper node exists (e.g. cited-but-not-ingested or user-deleted -> ingested=false),
                        # we allow importing to "fill in" the stub without forcing a conflict workflow.
                        if bool(p.get("ingested")):
                            u.status = "conflict"
                    except KeyError:
                        pass
        except Exception as exc:  # noqa: BLE001
            # If Neo4j isn't reachable, keep status=ready but record a scan-level error.
            errors.append({"error": f"Neo4j check failed: {exc}"})

    out = {
        "upload_id": upload_id,
        "mode": m.mode,
        "doi_strategy": doi_strategy,
        "root": str(root),
        "units": [asdict(u) for u in units],
        "errors": errors,
    }

    p = scan_path(upload_id)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return out
