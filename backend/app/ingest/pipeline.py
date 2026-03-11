from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.citations.aggregate import build_reference_and_cite_records
from app.citations.citation_event_recovery import recover_citation_events_from_references
from app.crossref.client import CrossrefClient
from app.extraction.orchestrator import run_phase1_extraction
from app.graph.neo4j_client import Neo4jClient
from app.graph.neo4j_client import paper_id_for_md_path
from app.ingest.figures import extract_figures_from_markdown
from app.ingest.models import DocumentIR
from app.ingest.paper_meta import load_canonical_meta
from app.ingest.parse_md import find_mineru_markdowns, parse_mineru_markdown
from app.llm.citation_purpose import classify_citation_purposes_batch
from app.llm.reference_recovery import recover_references_with_agent
from app.rag.structured_retrieval import build_community_corpus_rows
from app.schema_store import load_active, normalize_paper_type
from app.settings import settings
from app.vector.faiss_store import build_faiss_for_chunks, build_faiss_for_rows


ProgressFn = Callable[[str, float, str | None], None]
logger = logging.getLogger(__name__)


def _safe_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s or ""))


# 同一 ingest 批次内缓存 paper_type 结果，避免重复 LLM 调用
_paper_type_cache: dict[str, str] = {}


def _paper_type_cache_clear() -> None:
    """Clear the per-batch paper type cache (call at batch start)."""
    _paper_type_cache.clear()


def _paper_type_for_md(md_path: str, doc: DocumentIR | None = None) -> str:
    """Detect paper type: cache > meta.json > LLM > rule-based > 'research'."""
    cache_key = str(md_path)
    if cache_key in _paper_type_cache:
        return _paper_type_cache[cache_key]

    meta = load_canonical_meta(md_path)
    meta_pt = str(meta.get("paper_type") or "").strip().lower() or None

    result: str | None = None
    if doc is not None:
        try:
            from app.llm.paper_type_classifier import (
                classify_paper_type,
                extract_abstract_from_chunks,
                extract_section_headings_from_chunks,
            )
            title = doc.paper.title or doc.paper.title_alt or ""
            abstract = extract_abstract_from_chunks(doc.chunks)
            headings = extract_section_headings_from_chunks(doc.chunks)
            result = classify_paper_type(
                title=title,
                abstract=abstract,
                section_headings=headings,
                meta_paper_type=meta_pt,
            )
        except Exception:
            logger.warning("paper_type classification failed for %s", md_path, exc_info=True)

    if result is None:
        result = normalize_paper_type(meta_pt)

    _paper_type_cache[cache_key] = result
    return result


def _schema_for_md(md_path: str, doc: DocumentIR | None = None) -> dict:
    paper_type = _paper_type_for_md(md_path, doc=doc)
    try:
        return load_active(paper_type)  # type: ignore[arg-type]
    except Exception:
        return load_active("research")  # type: ignore[arg-type]


def _bounded_int(value: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = int(default)
    return max(lo, min(hi, n))


def _write_document_ir(path: Path, doc: DocumentIR) -> None:
    path.write_text(
        json.dumps(
            {
                "paper": doc.paper.__dict__,
                "chunks": [
                    {
                        **c.__dict__,
                        "span": c.span.__dict__,
                    }
                    for c in doc.chunks
                ],
                "references": [r.__dict__ for r in doc.references],
                "citations": [
                    {
                        **ce.__dict__,
                        "span": ce.span.__dict__,
                    }
                    for ce in doc.citations
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def ingest_markdowns(md_files: list[str], progress: ProgressFn | None = None) -> dict:
    def notify(stage: str, p: float, msg: str | None = None) -> None:
        if progress:
            progress(stage, p, msg)

    if not md_files:
        raise FileNotFoundError("No markdown files provided")

    _paper_type_cache_clear()

    notify("ingest:init", 0.06, "Preparing run directory")
    run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(__file__).resolve().parents[2] / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir.parent / "LATEST").write_text(run_id, encoding="utf-8")

    notify("ingest:parse", 0.12, f"Parsing {len(md_files)} markdown(s)")
    parsed = []
    for md in md_files:
        doc = parse_mineru_markdown(md)
        parsed.append(doc)
        out = run_dir / f"{doc.paper.paper_source}.document_ir.json"
        _write_document_ir(out, doc)

    notify("ingest:reference_recovery", 0.24, "Recovering references for papers with missing/low parsed refs")
    reference_recovery: list[dict] = [{} for _ in parsed]

    def _recover_refs(idx: int, doc: DocumentIR) -> tuple[int, DocumentIR, dict]:
        schema_for_recovery = _schema_for_md(doc.paper.md_path, doc=doc)
        recovered_doc, rr = recover_references_with_agent(
            doc,
            prompt_overrides=schema_for_recovery.get("prompts"),
            rules=schema_for_recovery.get("rules"),
        )
        rr["paper_source"] = doc.paper.paper_source
        rr["paper_id"] = paper_id_for_md_path(recovered_doc.paper.md_path, doi=recovered_doc.paper.doi)
        rr["schema_version"] = int(schema_for_recovery.get("version") or 1)
        rr["schema_paper_type"] = str(schema_for_recovery.get("paper_type") or "research")
        return idx, recovered_doc, rr

    pre_llm_workers = min(settings.ingest_pre_llm_max_workers, len(parsed))
    pre_llm_workers = max(1, pre_llm_workers)

    if pre_llm_workers == 1 or len(parsed) <= 1:
        for idx, doc in enumerate(parsed):
            _, recovered_doc, rr = _recover_refs(idx, doc)
            parsed[idx] = recovered_doc
            reference_recovery[idx] = rr
    else:
        from concurrent.futures import ThreadPoolExecutor as _PreLLMPool

        with _PreLLMPool(max_workers=pre_llm_workers) as executor:
            futures = [executor.submit(_recover_refs, idx, doc) for idx, doc in enumerate(parsed)]
            for future in futures:
                idx, recovered_doc, rr = future.result()
                parsed[idx] = recovered_doc
                reference_recovery[idx] = rr

    # Write artifacts (serial — I/O is fast, keeps ordering deterministic)
    for idx, rr in enumerate(reference_recovery):
        doc = parsed[idx]
        before_refs = len(doc.references or [])
        rr_path = run_dir / f"{doc.paper.paper_source}.reference_recovery.json"
        rr_path.write_text(json.dumps(rr, ensure_ascii=False, indent=2), encoding="utf-8")
        if int(rr.get("after_refs") or before_refs) != before_refs:
            out = run_dir / f"{doc.paper.paper_source}.document_ir.json"
            _write_document_ir(out, doc)

    # ── Stage barrier: all reference recovery complete before citation event recovery ──

    notify("ingest:citation_event_recovery", 0.30, "Recovering citation events from references when needed")
    citation_event_recovery: list[dict] = [{} for _ in parsed]

    def _recover_events(idx: int, doc: DocumentIR) -> tuple[int, DocumentIR, dict]:
        schema_for_recovery = _schema_for_md(doc.paper.md_path, doc=doc)
        recovered_doc, cer = recover_citation_events_from_references(
            doc,
            rules=schema_for_recovery.get("rules"),
        )
        cer["paper_source"] = doc.paper.paper_source
        cer["paper_id"] = paper_id_for_md_path(recovered_doc.paper.md_path, doi=recovered_doc.paper.doi)
        cer["schema_version"] = int(schema_for_recovery.get("version") or 1)
        cer["schema_paper_type"] = str(schema_for_recovery.get("paper_type") or "research")
        return idx, recovered_doc, cer

    if pre_llm_workers == 1 or len(parsed) <= 1:
        for idx, doc in enumerate(parsed):
            _, recovered_doc, cer = _recover_events(idx, doc)
            parsed[idx] = recovered_doc
            citation_event_recovery[idx] = cer
    else:
        with _PreLLMPool(max_workers=pre_llm_workers) as executor:
            futures = [executor.submit(_recover_events, idx, doc) for idx, doc in enumerate(parsed)]
            for future in futures:
                idx, recovered_doc, cer = future.result()
                parsed[idx] = recovered_doc
                citation_event_recovery[idx] = cer

    # Write artifacts (serial)
    for idx, cer in enumerate(citation_event_recovery):
        doc = parsed[idx]
        cer_path = run_dir / f"{doc.paper.paper_source}.citation_event_recovery.json"
        cer_path.write_text(json.dumps(cer, ensure_ascii=False, indent=2), encoding="utf-8")
        if int(cer.get("after_events") or 0) != int(cer.get("before_events") or 0):
            out = run_dir / f"{doc.paper.paper_source}.document_ir.json"
            _write_document_ir(out, doc)

    notify("ingest:crossref", 0.35, "Resolving references via Crossref")
    crossref = CrossrefClient()
    cite_records = []
    for doc in parsed:
        try:
            # Read crossref_confidence_threshold from schema
            schema_for_crossref = _schema_for_md(doc.paper.md_path, doc=doc)
            raw_threshold = (schema_for_crossref.get("rules") or {}).get("crossref_confidence_threshold", 0.55)
            try:
                crossref_threshold = float(raw_threshold)
            except Exception:  # noqa: BLE001
                crossref_threshold = 0.55
            crossref_threshold = max(0.0, min(1.0, crossref_threshold))

            rec = build_reference_and_cite_records(
                doc,
                crossref=crossref,
                crossref_confidence_threshold=crossref_threshold,
            )
            cite_records.append(rec)
            out = run_dir / f"{doc.paper.paper_source}.citations.json"
            out.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            cite_records.append(
                {
                    "paper_id": None,
                    "error": str(exc),
                    "paper_source": doc.paper.paper_source,
                }
            )

    notify("ingest:neo4j", 0.52, "Writing to Neo4j (papers, chunks, cites)")
    neo4j_written = False
    neo4j_error = None
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.ensure_schema()
            for doc in parsed:
                # Re-ingest idempotency fix: delete stale subgraph if paper already exists
                paper_id = paper_id_for_md_path(doc.paper.md_path, doi=doc.paper.doi)
                try:
                    client.get_paper_basic(paper_id)
                except KeyError:
                    # Paper doesn't exist yet - first ingest, no stale data to clean
                    pass
                else:
                    # Paper exists - delete stale chunks/claims/logic/refs/cites before upserting
                    client.delete_paper_subgraph(paper_id)

                client.upsert_paper_and_chunks(doc)
                try:
                    paper_type = _paper_type_for_md(doc.paper.md_path, doc=doc)
                    schema = load_active(paper_type)  # type: ignore[arg-type]
                    client.update_paper_props(
                        paper_id,
                        {
                            "paper_type": paper_type,
                            "schema_paper_type": paper_type,
                            "schema_version": int(schema.get("version") or 1),
                        },
                    )
                except Exception:
                    pass
                try:
                    figs = extract_figures_from_markdown(paper_id=paper_id, md_path=doc.paper.md_path)
                    client.upsert_figures(
                        paper_id,
                        [
                            {
                                "figure_id": f.figure_id,
                                "paper_id": paper_id,
                                "md_path": f.md_path,
                                "rel_path": f.rel_path,
                                "filename": f.filename,
                                "img_line": f.img_line,
                                "caption_text": f.caption_text,
                                "caption_start_line": f.caption_start_line,
                                "caption_end_line": f.caption_end_line,
                            }
                            for f in figs
                        ],
                    )
                except Exception:
                    # figures are optional; do not fail ingestion
                    pass
            for rec in cite_records:
                if not rec or not rec.get("paper_id"):
                    continue
                client.upsert_references_and_citations(
                    paper_id=rec["paper_id"],
                    refs=rec["refs"],
                    cited_papers=rec["cited_papers"],
                    cites_resolved=rec["cites_resolved"],
                    cites_unresolved=rec["cites_unresolved"],
                )
            neo4j_written = True
    except Exception as exc:  # noqa: BLE001
        neo4j_error = str(exc)

    notify("ingest:llm", 0.70, "Running LLM extraction (Logic/Claims/Citation Purposes)")
    llm_built = False
    llm_error = None
    llm_outputs: list[dict[str, Any]] = []
    llm_failures: list[str] = []

    def _llm_extract_one(idx: int, doc: DocumentIR, rec: dict[str, Any]) -> dict[str, Any]:
        paper_id = str(rec["paper_id"])

        paper_type = _paper_type_for_md(doc.paper.md_path, doc=doc)
        schema = load_active(paper_type)  # type: ignore[arg-type]
        phase1_artifacts_dir = run_dir / "raw_pool" / _safe_id(paper_id)
        phase1 = run_phase1_extraction(
            doc=doc,
            paper_id=paper_id,
            cite_rec=rec,
            schema=schema,
            artifacts_dir=phase1_artifacts_dir,
            allow_weak=bool(getattr(settings, "phase1_gate_allow_weak", False)),
        )
        step_order = list(phase1.get("step_order") or [])
        logic_claims = {
            "logic": phase1.get("logic") or {},
            "claims": phase1.get("validated_claims") or [],
            "quality_report": phase1.get("quality_report") or {},
            "raw_claim_candidates": len(phase1.get("claim_candidates") or []),
            "raw_claims_merged": len(phase1.get("claims_merged") or []),
            "rejected_claims": len(phase1.get("rejected_claims") or []),
        }
        llm_out = {"paper_id": paper_id, "schema": {"paper_type": paper_type, "version": schema.get("version")}, **logic_claims}
        out = run_dir / f"{doc.paper.paper_source}.llm_imrad.json"
        out.write_text(json.dumps(logic_claims, ensure_ascii=False, indent=2), encoding="utf-8")

        purposes = []
        chunk_by_id = {c.chunk_id: c for c in doc.chunks}
        citing_title = doc.paper.title or doc.paper.title_alt or doc.paper.paper_source
        batch_in = []
        for cr in rec.get("cites_resolved") or []:
            cited_paper_id = cr.get("cited_paper_id")
            cited_doi = None
            if cited_paper_id and str(cited_paper_id).startswith("doi:"):
                cited_doi = str(cited_paper_id)[4:]
            cited_title = None
            for cp in rec.get("cited_papers") or []:
                if cp.get("paper_id") == cited_paper_id:
                    cited_title = cp.get("title")
                    break
            contexts = []
            for cid in cr.get("evidence_chunk_ids") or []:
                ch = chunk_by_id.get(cid)
                if ch and ch.text:
                    contexts.append(ch.text)
            batch_in.append(
                {
                    "cited_paper_id": cited_paper_id,
                    "cited_title": cited_title,
                    "cited_doi": cited_doi,
                    "contexts": contexts,
                }
            )
        batch_out = classify_citation_purposes_batch(
            citing_title=citing_title,
            cites=batch_in,
            prompt_overrides=schema.get("prompts"),
            rules=schema.get("rules"),
        )
        by_id = batch_out.get("by_id") or {}
        for cr in rec.get("cites_resolved") or []:
            cited_paper_id = cr.get("cited_paper_id")
            if not cited_paper_id:
                continue
            x = by_id.get(str(cited_paper_id)) or {"labels": ["Unknown"], "scores": [0.0]}
            purposes.append({"cited_paper_id": cited_paper_id, "labels": x["labels"], "scores": x["scores"]})
        out2 = run_dir / f"{doc.paper.paper_source}.llm_citation_purposes.json"
        out2.write_text(json.dumps(purposes, ensure_ascii=False, indent=2), encoding="utf-8")

        llm_out["citation_purposes"] = purposes
        return {
            "idx": idx,
            "paper_id": paper_id,
            "paper_year": doc.paper.year,
            "step_order": step_order,
            "logic_claims": logic_claims,
            "citation_purposes": purposes,
            "llm_out": llm_out,
        }

    def _write_llm_to_neo4j(item: dict[str, Any]) -> None:
        paper_id = str(item["paper_id"])
        logic_claims = dict(item.get("logic_claims") or {})
        claims = list(logic_claims.get("claims") or [])
        step_order = list(item.get("step_order") or [])
        purposes = list(item.get("citation_purposes") or [])
        quality_report = logic_claims.get("quality_report") or {}
        gate_passed = bool(quality_report.get("gate_passed"))
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            if not gate_passed:
                try:
                    client.update_paper_props(
                        paper_id,
                        {
                            "paper_rebuild_status": "gate_failed",
                            "phase1_gate_passed": False,
                            "phase1_quality_json": json.dumps(quality_report, ensure_ascii=False),
                            "phase1_quality_tier": str(quality_report.get("quality_tier") or ""),
                            "phase1_quality_tier_score": float(quality_report.get("quality_tier_score") or 0.0),
                        },
                    )
                except Exception:
                    pass
                return
            client.upsert_logic_steps_and_claims(
                paper_id=paper_id,
                logic=logic_claims.get("logic") or {},
                claims=claims,
                step_order=step_order,
            )
            try:
                quality_report = logic_claims.get("quality_report") or {}
                client.update_paper_props(
                    paper_id,
                    {
                        "phase1_quality_json": json.dumps(quality_report, ensure_ascii=False),
                        "phase1_gate_passed": bool(quality_report.get("gate_passed")),
                        "phase1_quality_tier": str(quality_report.get("quality_tier") or ""),
                        "phase1_quality_tier_score": float(quality_report.get("quality_tier_score") or 0.0),
                    },
                )
            except Exception:
                pass
            try:
                client.apply_human_claim_evidence_overrides(paper_id)
            except Exception:
                pass
            try:
                client.apply_human_logic_step_evidence_overrides(paper_id)
            except Exception:
                pass
            for p in purposes:
                if not p.get("cited_paper_id"):
                    continue
                client.update_cites_purposes(
                    citing_paper_id=paper_id,
                    cited_paper_id=p["cited_paper_id"],
                    labels=p["labels"],
                    scores=p["scores"],
                )

            # P1 Fix: Backfill any remaining missing citation purposes (defense-in-depth)
            # This catches edge cases where purpose labels weren't set during reference resolution
            try:
                backfilled_count = client.backfill_missing_citation_purposes(
                    citing_paper_id=paper_id,
                    default_label="Background",
                    default_score=0.2,
                )
                if backfilled_count > 0:
                    logger.info(
                        "Backfilled %d missing citation purpose labels for paper_id=%s",
                        backfilled_count,
                        paper_id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to backfill citation purposes for paper_id=%s: %s",
                    paper_id,
                    str(e),
                    exc_info=True,  # Include stack trace for debugging
                )

    try:
        jobs = [(idx, doc, rec) for idx, (doc, rec) in enumerate(zip(parsed, cite_records)) if rec.get("paper_id")]
        total_jobs = len(jobs)
        if total_jobs == 0:
            llm_built = True
        else:
            configured_workers = _bounded_int(
                getattr(settings, "ingest_llm_max_workers", 4),
                default=4,
                lo=1,
                hi=16,
            )
            max_workers = min(total_jobs, configured_workers)
            completed = 0
            outputs_by_idx: dict[int, dict[str, Any]] = {}
            notify(
                "ingest:llm",
                0.70,
                f"Running LLM extraction (Logic/Claims/Citation Purposes) (0/{total_jobs}, workers={max_workers})",
            )
            heartbeat_seconds = _bounded_int(
                getattr(settings, "ingest_llm_heartbeat_seconds", 20),
                default=20,
                lo=5,
                hi=120,
            )
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ingest-llm") as executor:
                future_map = {
                    executor.submit(_llm_extract_one, idx, doc, rec): (idx, rec)
                    for idx, doc, rec in jobs
                }
                pending = set(future_map.keys())
                started_at = {future: time.monotonic() for future in pending}

                while pending:
                    done, pending = wait(
                        pending,
                        timeout=float(heartbeat_seconds),
                        return_when=FIRST_COMPLETED,
                    )

                    if not done:
                        # Heartbeat: no futures completed in this interval
                        ratio = completed / total_jobs
                        now = time.monotonic()
                        slowest_future = max(pending, key=lambda f: now - started_at.get(f, now))
                        _, slowest_rec = future_map[slowest_future]
                        slowest_paper_id = str(slowest_rec.get("paper_id") or "")
                        slowest_secs = int(max(0.0, now - started_at.get(slowest_future, now)))
                        notify(
                            "ingest:llm",
                            0.70 + (0.20 * ratio),
                            (
                                "Running LLM extraction (Logic/Claims/Citation Purposes) "
                                f"({completed}/{total_jobs}, running={len(pending)}, "
                                f"slowest={slowest_paper_id}:{slowest_secs}s, failed={len(llm_failures)})"
                            ),
                        )
                        continue

                    for future in done:
                        idx, rec = future_map[future]
                        paper_id = str(rec.get("paper_id") or "")
                        completed += 1

                        try:
                            item = future.result()
                        except Exception as exc:
                            logger.exception(f"LLM extraction failed for {paper_id}")
                            llm_failures.append(f"{paper_id}: {exc}")

                            # Write detailed error to file for debugging
                            try:
                                error_file = run_dir / f"{paper_id}.llm_error.txt"
                                error_file.write_text(
                                    f"Paper: {paper_id}\n"
                                    f"Error: {exc}\n"
                                    f"Type: {type(exc).__name__}\n",
                                    encoding="utf-8"
                                )
                            except Exception:
                                pass  # Don't fail if error logging fails

                            ratio = completed / total_jobs
                            notify(
                                "ingest:llm",
                                0.70 + (0.20 * ratio),
                                (
                                    "Running LLM extraction (Logic/Claims/Citation Purposes) "
                                    f"({completed}/{total_jobs}, running={len(pending)}, failed={len(llm_failures)})"
                                ),
                            )
                            continue

                        outputs_by_idx[idx] = dict(item["llm_out"])
                        ratio = completed / total_jobs
                        notify(
                            "ingest:llm",
                            0.70 + (0.20 * ratio),
                            (
                                "Running LLM extraction (Logic/Claims/Citation Purposes) "
                                f"({completed}/{total_jobs}, running={len(pending)}, failed={len(llm_failures)})"
                            ),
                        )

                        if neo4j_written:
                            try:
                                _write_llm_to_neo4j(item)
                            except Exception as exc:
                                llm_failures.append(f"{paper_id}: neo4j write failed: {exc}")
                                ratio = completed / total_jobs
                                notify(
                                    "ingest:llm",
                                    0.70 + (0.20 * ratio),
                                    (
                                        "Running LLM extraction (Logic/Claims/Citation Purposes) "
                                        f"({completed}/{total_jobs}, running={len(pending)}, failed={len(llm_failures)})"
                                    ),
                                )
            llm_outputs = [outputs_by_idx[i] for i in sorted(outputs_by_idx)]
            if llm_failures:
                shown = llm_failures[:5]
                llm_error = "; ".join(shown)
                if len(llm_failures) > len(shown):
                    llm_error = f"{llm_error}; ... ({len(llm_failures)} failures total)"
            llm_built = not llm_failures

    except Exception as exc:  # noqa: BLE001
        llm_error = str(exc)

    notify("ingest:faiss", 0.90, "Building FAISS index")
    faiss_built = False
    faiss_error = None
    faiss_dir = str(run_dir / "faiss")
    try:
        faiss_root = Path(faiss_dir)
        all_chunks = [c for d in parsed for c in d.chunks if c.kind != "heading"]
        build_faiss_for_chunks(all_chunks, out_dir=str(faiss_root / "chunks"))
        if neo4j_written:
            with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
                structured_corpora = {
                    "logic_steps": (
                        client.list_logic_step_structured_rows(limit=50000),
                        [
                            "kind",
                            "source_id",
                            "paper_id",
                            "paper_source",
                            "step_type",
                            "evidence_chunk_ids",
                            "evidence_quote",
                        ],
                    ),
                    "claims": (
                        client.list_claim_structured_rows(limit=50000),
                        [
                            "kind",
                            "source_id",
                            "paper_id",
                            "paper_source",
                            "step_type",
                            "confidence",
                            "community_id",
                            "evidence_chunk_ids",
                            "evidence_quote",
                        ],
                    ),
                    "communities": (
                        build_community_corpus_rows(client, limit=50000, member_limit=200),
                        [
                            "kind",
                            "source_id",
                            "community_id",
                            "title",
                            "summary",
                            "keyword_texts",
                            "member_ids",
                            "member_kinds",
                            "paper_id",
                            "paper_source",
                            "textbook_id",
                            "chapter_id",
                        ],
                    ),
                }
            for corpus, (rows, metadata_keys) in structured_corpora.items():
                if not rows:
                    continue
                build_faiss_for_rows(
                    rows,
                    out_dir=str(faiss_root / corpus),
                    text_key="text",
                    metadata_keys=metadata_keys,
                )
        faiss_built = True
    except Exception as exc:  # noqa: BLE001
        faiss_error = str(exc)

    clustering: dict[str, Any] = {
        "triggered": False,
        "status": "disabled",
        "reason": "community_corpus_replaces_legacy_clustering",
    }

    notify("ingest:done", 1.0, "Done")
    return {
        "run_id": run_id,
        "md_files": md_files,
        "papers": [
            {
                "paper_source": d.paper.paper_source,
                "md_path": d.paper.md_path,
                "chunks": len(d.chunks),
                "references": len(d.references),
                "citation_events": len(d.citations),
                "doi": d.paper.doi,
                "title": d.paper.title,
                "year": d.paper.year,
            }
            for d in parsed
        ],
        "citations_built": [
            {
                "paper_id": r.get("paper_id"),
                "refs": len(r.get("refs") or []),
                "cites_resolved": len(r.get("cites_resolved") or []),
                "cites_unresolved": len(r.get("cites_unresolved") or []),
                "error": r.get("error"),
                "paper_source": r.get("paper_source"),
            }
            for r in cite_records
        ],
        "reference_recovery": reference_recovery,
        "citation_event_recovery": citation_event_recovery,
        "neo4j_written": neo4j_written,
        "neo4j_error": neo4j_error,
        "llm_built": llm_built,
        "llm_error": llm_error,
        "phase1_quality": [
            {
                "paper_id": o.get("paper_id"),
                "gate_passed": bool((o.get("quality_report") or {}).get("gate_passed")),
                "quality_tier": str((o.get("quality_report") or {}).get("quality_tier") or ""),
                "quality_tier_score": (o.get("quality_report") or {}).get("quality_tier_score"),
                "supported_claim_ratio": (o.get("quality_report") or {}).get("supported_claim_ratio"),
                "step_coverage_ratio": (o.get("quality_report") or {}).get("step_coverage_ratio"),
                "validated_claims": len(o.get("claims") or []),
            }
            for o in llm_outputs
        ],
        "faiss_built": faiss_built,
        "faiss_error": faiss_error,
        "faiss_dir": faiss_dir,
        "clustering": clustering,
        "artifacts_dir": str(run_dir),
    }


def ingest_path(root_path: str, progress: ProgressFn | None = None) -> dict:
    def notify(stage: str, p: float, msg: str | None = None) -> None:
        if progress:
            progress(stage, p, msg)

    notify("ingest:scan", 0.02, f"Scanning markdowns under {root_path}")
    md_files = find_mineru_markdowns(root_path)
    if not md_files:
        raise FileNotFoundError(f"No markdown files found under: {root_path}")
    return ingest_markdowns(md_files, progress=progress)
