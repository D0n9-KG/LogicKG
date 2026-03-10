"""Textbook ingestion pipeline.

Orchestrates the full flow: split → md-to-json → Youtu upload →
download graph → import into LogicKG Neo4j.

autoyoutu is invoked as a **subprocess** (not imported) to keep a
clean dependency boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from app.graph.neo4j_client import Neo4jClient
from app.ingest.graph_importer import import_youtu_graph
from app.ingest.textbook_proposition_mapper import map_entities_to_propositions
from app.ingest.textbook_splitter import ChapterUnit, split_textbook_md
from app.settings import settings

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, float, str | None], None]
LogFn = Callable[[str], None]


def _noop_progress(stage: str, p: float, msg: str | None = None) -> None:
    pass


def _noop_log(line: str) -> None:
    pass


def _textbook_id(title: str, authors: list[str] | None) -> str:
    """Deterministic textbook ID from title + authors."""
    authors_joined = ",".join(sorted(str(a).strip().lower() for a in (authors or []) if str(a).strip()))
    seed = f"tb:v1\0{(title or '').strip().lower()}\0{authors_joined}"
    return "tb:" + hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _chapter_id(textbook_id: str, chapter_num: int) -> str:
    return f"{textbook_id}:ch{chapter_num:03d}"


_INVALID_FS_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _textbook_storage_name(textbook_id: str) -> str:
    """Create a filesystem-safe directory name for textbook artifacts."""
    raw = str(textbook_id or "").strip()
    if not raw:
        return "tb_unknown"
    safe = _INVALID_FS_CHARS_RE.sub("_", raw).rstrip(" .")
    return safe or "tb_unknown"


def _autoyoutu_dataset_name(chapter_md_path: Path, output_dir: Path) -> str:
    """Generate a chapter-scoped dataset name for autoyoutu/GraphRAG."""
    stem = _INVALID_FS_CHARS_RE.sub("_", chapter_md_path.stem).strip(" .") or "chapter"
    suffix = hashlib.sha256(
        str(output_dir.resolve()).encode("utf-8", errors="ignore")
    ).hexdigest()[:8]
    return f"{stem}_{suffix}"


def _run_autoyoutu_pipeline(
    chapter_md_path: Path,
    output_dir: Path,
    log: LogFn,
) -> Path | None:
    """Run autoyoutu integrated_pipeline.py as a subprocess.

    The pipeline converts MD → JSON → uploads to Youtu → downloads
    the resulting graph.json.  We reuse autoyoutu's own
    ``IntegratedPipeline`` via its CLI entry-point.

    Returns the path to the downloaded graph JSON, or None on failure.
    """
    autoyoutu_dir = Path(settings.autoyoutu_dir).resolve()
    if not autoyoutu_dir.is_dir():
        raise FileNotFoundError(f"autoyoutu directory not found: {autoyoutu_dir}")

    script = autoyoutu_dir / "integrated_pipeline.py"
    if not script.is_file():
        raise FileNotFoundError(f"integrated_pipeline.py not found in {autoyoutu_dir}")

    # autoyoutu expects an input directory containing .md files
    chapter_input_dir = output_dir / "md_input"
    chapter_input_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(chapter_md_path), str(chapter_input_dir / chapter_md_path.name))

    import subprocess
    import os

    child_env = os.environ.copy()
    # Force UTF-8 stdio for autoyoutu subprocess on Windows to avoid
    # UnicodeEncodeError when printing non-ASCII/emoji logs.
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    # Isolate converted JSON artifacts per chapter run to avoid cross-run pollution
    # from autoyoutu's shared default output directory.
    child_env["MD_OUTPUT_DIR"] = str(output_dir / "converted_json")
    # Force graph download artifacts to a chapter-local directory and keep files
    # so LogicKG can import the produced graph JSON.
    graph_download_dir = output_dir / "graph_data"
    graph_download_dir.mkdir(parents=True, exist_ok=True)
    child_env["LOCAL_TEMP_DIR"] = str(graph_download_dir)
    child_env["CLEANUP_TEMP_FILES"] = "false"
    child_env["DATASET_NAME"] = _autoyoutu_dataset_name(chapter_md_path, output_dir)

    cmd = [
        sys.executable,
        str(script),
        str(chapter_input_dir),
        "--no-clear-data",
    ]
    log(f"Running autoyoutu: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(autoyoutu_dir),
        env=child_env,
        timeout=3600,  # 1 hour max per chapter
    )

    if result.returncode != 0:
        log(f"autoyoutu failed (rc={result.returncode}): {result.stderr[:500]}")
        return None

    log(f"autoyoutu stdout (last 300 chars): {result.stdout[-300:]}")

    # Find the downloaded graph JSON.
    graph_files: list[Path] = []
    search_dirs = [
        graph_download_dir,          # preferred: per-chapter isolated dir
        autoyoutu_dir / "temp_graphs",  # legacy fallback
        autoyoutu_dir / "Graph_Data",   # autoyoutu default local temp dir
    ]
    for d in search_dirs:
        if d.is_dir():
            graph_files.extend(d.glob("*.json"))

    graph_files = sorted(graph_files, key=lambda p: p.stat().st_mtime, reverse=True)
    if not graph_files:
        log("No graph JSON files found after autoyoutu run")
        return None

    latest = graph_files[0]
    # Copy to our output directory for traceability
    dest = output_dir / f"graph_{chapter_md_path.stem}.json"
    shutil.copy2(str(latest), str(dest))
    log(f"Graph JSON copied to {dest}")
    return dest


def ingest_textbook(
    md_path: str,
    metadata: dict[str, Any],
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Full textbook ingestion pipeline.

    Args:
        md_path: Path to the textbook ``.md`` file.
        metadata: ``{title, authors, year, edition, doc_type}``.
        progress: ``(stage, 0-1, msg)`` callback.
        log: Line-level log callback.

    Returns:
        Summary dict with counts and chapter details.
    """
    progress = progress or _noop_progress
    log = log or _noop_log

    title = str(metadata.get("title") or Path(md_path).stem)
    authors = metadata.get("authors") or []
    year = metadata.get("year")
    edition = metadata.get("edition")
    doc_type = str(metadata.get("doc_type") or "textbook")

    tb_id = _textbook_id(title, authors)
    log(f"Textbook ID: {tb_id}")

    # ── Step 1: Split into chapters ──
    progress("textbook:split", 0.02, f"Splitting {Path(md_path).name} into chapters")
    chapters = split_textbook_md(md_path)
    log(f"Split into {len(chapters)} chapters")

    if not chapters:
        return {"ok": False, "error": "No chapters found in markdown file"}

    # ── Step 2: Create Textbook node ──
    progress("textbook:neo4j:textbook", 0.05, "Creating Textbook node")

    # Persistent storage directory for graph JSONs
    storage_base = Path(settings.storage_dir) / "textbooks" / _textbook_storage_name(tb_id)
    storage_base.mkdir(parents=True, exist_ok=True)

    work_dir = Path(tempfile.mkdtemp(prefix="logickg_tb_"))
    log(f"Working directory: {work_dir}")

    total_entities = 0
    total_relations = 0
    chapter_results: list[dict] = []
    proposition_result = {"entities": 0, "propositions": 0}

    try:
        # Single Neo4j connection for the entire ingestion
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.ensure_schema()
            client.upsert_textbook(
                textbook_id=tb_id,
                title=title,
                authors=authors,
                year=int(year) if year is not None else None,
                edition=edition,
                doc_type=doc_type,
                source_dir=str(Path(md_path).parent),
                total_chapters=len(chapters),
            )

            # ── Step 3: Process each chapter ──
            for idx, ch in enumerate(chapters):
                ch_id = _chapter_id(tb_id, ch.chapter_num)
                ch_progress_base = 0.05 + (idx / max(1, len(chapters))) * 0.85
                progress(
                    "textbook:chapter",
                    ch_progress_base,
                    f"Processing chapter {ch.chapter_num}: {ch.title}",
                )
                log(f"── Chapter {ch.chapter_num}: {ch.title} ({len(ch.body)} chars) ──")

                # Create chapter node BEFORE graph import (so HAS_ENTITY works)
                client.upsert_textbook_chapter(
                    chapter_id=ch_id,
                    textbook_id=tb_id,
                    chapter_num=ch.chapter_num,
                    title=ch.title,
                )

                # Save chapter markdown to temp dir
                ch_dir = work_dir / f"ch{ch.chapter_num:03d}"
                ch_dir.mkdir(parents=True, exist_ok=True)
                ch_md = ch_dir / f"chapter_{ch.chapter_num:03d}.md"
                ch_md.write_text(ch.body, encoding="utf-8")

                # Run autoyoutu pipeline (subprocess)
                graph_json = _run_autoyoutu_pipeline(ch_md, ch_dir, log)

                entity_count = 0
                relation_count = 0
                community_count = 0
                stored_graph_path: str | None = None

                if graph_json and graph_json.is_file():
                    # Copy graph JSON to persistent storage
                    dest_name = f"graph_ch{ch.chapter_num:03d}.json"
                    stored = storage_base / dest_name
                    shutil.copy2(str(graph_json), str(stored))
                    stored_graph_path = str(stored)

                    progress(
                        "textbook:import",
                        ch_progress_base + 0.4 * (1 / max(1, len(chapters))),
                        f"Importing graph for chapter {ch.chapter_num}",
                    )
                    result = import_youtu_graph(
                        graph_json_path=str(graph_json),
                        textbook_id=tb_id,
                        chapter_id=ch_id,
                        neo4j_client=client,
                    )
                    entity_count = result.get("entity_count", 0)
                    relation_count = result.get("relation_count", 0)
                    community_count = result.get("community_count", 0)
                else:
                    log(f"WARNING: No graph produced for chapter {ch.chapter_num}")

                # Update chapter node with counts and graph file path
                client.upsert_textbook_chapter(
                    chapter_id=ch_id,
                    textbook_id=tb_id,
                    chapter_num=ch.chapter_num,
                    title=ch.title,
                    youtu_graph_file=stored_graph_path,
                    entity_count=entity_count,
                    relation_count=relation_count,
                )

                total_entities += entity_count
                total_relations += relation_count
                chapter_results.append({
                    "chapter_num": ch.chapter_num,
                    "title": ch.title,
                    "entity_count": entity_count,
                    "relation_count": relation_count,
                    "community_count": community_count,
                })
                log(f"Chapter {ch.chapter_num} done: {entity_count} entities, {relation_count} relations")

            # Step 4: map textbook assertion entities to Propositions.
            progress("textbook:proposition_map", 0.95, "Mapping textbook entities to propositions")
            candidate_entities = client.list_knowledge_entities_for_propositions(tb_id)
            mapped_items = map_entities_to_propositions(candidate_entities)
            proposition_result = client.upsert_proposition_for_entity(mapped_items)
            log(
                "Proposition mapping done: "
                f"{proposition_result.get('entities', 0)} entities mapped, "
                f"{proposition_result.get('propositions', 0)} propositions upserted"
            )

    finally:
        # Always clean up temp directory
        shutil.rmtree(work_dir, ignore_errors=True)

    progress("textbook:done", 1.0, "Textbook ingestion complete")
    summary = {
        "ok": True,
        "textbook_id": tb_id,
        "title": title,
        "total_chapters": len(chapters),
        "total_entities": total_entities,
        "total_relations": total_relations,
        "mapped_propositions": proposition_result.get("propositions", 0),
        "chapters": chapter_results,
    }
    log(f"Ingestion complete: {json.dumps(summary, ensure_ascii=False)}")
    return summary
