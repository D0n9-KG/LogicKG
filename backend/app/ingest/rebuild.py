from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.citations.aggregate import build_reference_and_cite_records
from app.citations.citation_event_recovery import recover_citation_events_from_references
from app.community.service import rebuild_global_communities
from app.crossref.client import CrossrefClient
from app.extraction.orchestrator import run_phase1_extraction
from app.graph.neo4j_client import Neo4jClient
from app.graph.neo4j_client import paper_id_for_md_path
from app.ingest.figures import extract_figures_from_markdown
from app.ingest.paper_meta import load_canonical_meta
from app.ingest.models import Chunk, MdSpan
from app.ingest.parse_md import parse_mineru_markdown
from app.llm.citation_purpose import classify_citation_purposes_batch
from app.llm.reference_recovery import recover_references_with_agent
from app.rag.structured_retrieval import build_community_corpus_rows
from app.schema_store import load_active, normalize_paper_type
from app.settings import settings
from app.vector.faiss_store import build_faiss_for_chunks, build_faiss_for_rows


ProgressFn = Callable[[str, float, str | None], None]
LogFn = Callable[[str], None]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _storage_dir() -> Path:
    p = _backend_root() / settings.storage_dir
    p.mkdir(parents=True, exist_ok=True)
    return p


def _clear_stale_legacy_faiss_exports(out_dir: Path) -> dict[str, Any]:
    removed: list[str] = []
    for name in ("propositions", "proposition_groups"):
        path = out_dir / name
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(str(path))
    return {"removed_corpora": removed}


def _safe_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


def _paper_type_for_md(md_path: str) -> str:
    try:
        meta = load_canonical_meta(md_path)
        return normalize_paper_type(meta.get("paper_type"))
    except Exception:
        return "research"


def _schema_for_md(md_path: str) -> dict[str, Any]:
    paper_type = _paper_type_for_md(md_path)
    try:
        return load_active(paper_type)  # type: ignore[arg-type]
    except Exception:
        return load_active("research")  # type: ignore[arg-type]


def cleanup_legacy_proposition_artifacts(
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    def notify(stage: str, p: float, msg: str | None = None) -> None:
        if progress:
            progress(stage, p, msg)

    def write_log(line: str) -> None:
        if log:
            log(line)

    notify("cleanup:legacy:init", 0.05, "Cleaning legacy proposition artifacts")
    out_dir = _storage_dir() / "faiss"
    faiss_cleanup = _clear_stale_legacy_faiss_exports(out_dir)
    if faiss_cleanup["removed_corpora"]:
        write_log(f"removed stale FAISS corpora: {', '.join(faiss_cleanup['removed_corpora'])}")

    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        notify("cleanup:legacy:graph", 0.2, "Deleting legacy proposition graph artifacts")
        graph_cleanup = client.clear_legacy_proposition_artifacts()
        notify("cleanup:legacy:schema", 0.32, "Dropping legacy proposition schema objects")
        schema_cleanup = client.drop_legacy_proposition_schema()

    write_log("legacy proposition artifacts removed from graph, schema, and stale FAISS exports")

    def community_progress(stage: str, p: float, msg: str | None = None) -> None:
        notify(stage, 0.4 + 0.35 * float(max(0.0, min(1.0, p))), msg)

    community = rebuild_global_communities(progress=community_progress, log=log)

    def faiss_progress(stage: str, p: float, msg: str | None = None) -> None:
        notify(stage, 0.78 + 0.17 * float(max(0.0, min(1.0, p))), msg)

    faiss = rebuild_global_faiss(progress=faiss_progress, log=log)
    notify("cleanup:legacy:done", 1.0, "Legacy proposition cleanup complete")
    return {
        "ok": True,
        "cleanup": {
            "graph": graph_cleanup,
            "schema": schema_cleanup,
            "removed_corpora": list(faiss_cleanup.get("removed_corpora") or []),
        },
        "community": community,
        "faiss": faiss,
    }


def rebuild_paper(
    paper_id: str,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    def notify(stage: str, p: float, msg: str | None = None) -> None:
        if progress:
            progress(stage, p, msg)

    def write_log(line: str) -> None:
        if log:
            log(line)

    notify("rebuild:load", 0.05, "Loading paper from Neo4j")
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        paper = client.get_paper_basic(paper_id)

    md_path = str(paper.get("source_md_path") or "").strip()
    if not md_path:
        raise FileNotFoundError(f"Paper has no source_md_path: {paper_id}")
    md_file = Path(md_path)
    if not md_file.exists():
        raise FileNotFoundError(f"Markdown not found on disk: {md_path}")

    expected_doi = None
    if paper_id.startswith("doi:"):
        expected_doi = paper_id[4:]

    notify("rebuild:parse", 0.15, "Parsing markdown")
    doc = parse_mineru_markdown(str(md_file))
    schema_for_recovery = _schema_for_md(doc.paper.md_path)
    notify("rebuild:reference_recovery", 0.20, "Recovering references via fallback agent")
    doc, reference_recovery = recover_references_with_agent(
        doc,
        prompt_overrides=schema_for_recovery.get("prompts"),
        rules=schema_for_recovery.get("rules"),
    )
    notify("rebuild:citation_event_recovery", 0.24, "Recovering citation events from references when needed")
    doc, citation_event_recovery = recover_citation_events_from_references(
        doc,
        rules=schema_for_recovery.get("rules"),
    )
    citation_event_recovery["paper_source"] = doc.paper.paper_source
    citation_event_recovery["paper_id"] = paper_id_for_md_path(doc.paper.md_path, doi=doc.paper.doi)
    citation_event_recovery["schema_version"] = int(schema_for_recovery.get("version") or 1)
    citation_event_recovery["schema_paper_type"] = str(schema_for_recovery.get("paper_type") or "research")
    expected_paper_id = paper_id_for_md_path(doc.paper.md_path, doi=doc.paper.doi)
    if expected_paper_id != paper_id:
        raise RuntimeError(
            f"paper_id mismatch: requested={paper_id!r}, parsed={expected_paper_id!r}. "
            "Refuse to rebuild to avoid overwriting a different paper."
        )

    notify("rebuild:crossref", 0.30, "Resolving references via Crossref")
    crossref = CrossrefClient()
    # Read crossref_confidence_threshold from schema
    try:
        meta = load_canonical_meta(doc.paper.md_path)
        paper_type = normalize_paper_type(meta.get("paper_type"))
        schema_for_crossref = load_active(paper_type)  # type: ignore[arg-type]
        raw_threshold = (schema_for_crossref.get("rules") or {}).get("crossref_confidence_threshold", 0.55)
        try:
            crossref_threshold = float(raw_threshold)
        except Exception:  # noqa: BLE001
            crossref_threshold = 0.55
        crossref_threshold = max(0.0, min(1.0, crossref_threshold))
    except Exception:  # noqa: BLE001
        crossref_threshold = 0.55
    cite_rec = build_reference_and_cite_records(doc, crossref=crossref, crossref_confidence_threshold=crossref_threshold)

    notify("rebuild:neo4j_clear", 0.42, "Clearing existing subgraph for this paper")
    notify("rebuild:neo4j_write", 0.50, "Writing rebuilt data to Neo4j")
    rebuild_started_at = datetime.now(tz=timezone.utc).isoformat()
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        client.ensure_schema()
        # Mark rebuild in-progress BEFORE deleting, so a partial rebuild is detectable
        try:
            client.update_paper_props(
                paper_id,
                {"paper_rebuild_status": "rebuilding", "paper_rebuild_started_at": rebuild_started_at},
            )
        except Exception:
            pass
        client.delete_paper_subgraph(paper_id)
        client.upsert_paper_and_chunks(doc)
        try:
            meta = load_canonical_meta(doc.paper.md_path)
            paper_type = normalize_paper_type(meta.get("paper_type"))
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
            pass
        if cite_rec.get("paper_id"):
            client.upsert_references_and_citations(
                paper_id=cite_rec["paper_id"],
                refs=cite_rec["refs"],
                cited_papers=cite_rec["cited_papers"],
                cites_resolved=cite_rec["cites_resolved"],
                cites_unresolved=cite_rec["cites_unresolved"],
            )

    notify("rebuild:llm", 0.68, "Running LLM extraction (Logic/Claims/Citation Purposes)")
    schema = _schema_for_md(doc.paper.md_path)
    phase1_artifacts_dir = _storage_dir() / "derived" / "papers" / _safe_id(paper_id) / "raw_pool"
    phase1 = run_phase1_extraction(
        doc=doc,
        paper_id=paper_id,
        cite_rec=cite_rec,
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

    purposes = []
    chunk_by_id = {c.chunk_id: c for c in doc.chunks}
    citing_title = doc.paper.title or doc.paper.title_alt or doc.paper.paper_source
    batch_in = []
    for cr in cite_rec.get("cites_resolved") or []:
        cited_paper_id = cr.get("cited_paper_id")
        cited_doi = None
        if cited_paper_id and str(cited_paper_id).startswith("doi:"):
            cited_doi = str(cited_paper_id)[4:]
        cited_title = None
        for cp in cite_rec.get("cited_papers") or []:
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
    for cr in cite_rec.get("cites_resolved") or []:
        cited_paper_id = cr.get("cited_paper_id")
        if not cited_paper_id:
            continue
        x = by_id.get(str(cited_paper_id)) or {"labels": ["Unknown"], "scores": [0.0]}
        purposes.append({"cited_paper_id": cited_paper_id, "labels": x["labels"], "scores": x["scores"]})

    notify("rebuild:neo4j_llm", 0.78, "Writing LLM outputs to Neo4j")

    # Phase1 gate: if quality gate failed, skip canonical Claim/LogicStep write
    # to prevent low-quality data from polluting the knowledge graph.
    quality_report = logic_claims.get("quality_report") or {}
    gate_passed = bool(quality_report.get("gate_passed"))
    if not gate_passed:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            try:
                client.update_paper_props(
                    paper_id,
                    {
                        "paper_rebuild_status": "gate_failed",
                        "phase1_gate_passed": False,
                        "phase1_quality_tier": str(quality_report.get("quality_tier") or ""),
                        "phase1_quality_tier_score": float(quality_report.get("quality_tier_score") or 0.0),
                        "phase1_quality_json": json.dumps(quality_report, ensure_ascii=False),
                    },
                )
            except Exception:
                pass
        notify(
            "rebuild:gate_failed",
            0.80,
            f"Phase1 gate failed (tier={quality_report.get('quality_tier')}), skipping canonical write",
        )
        write_log(f"gate_failed: paper_id={paper_id} tier={quality_report.get('quality_tier')}")
        return {
            "paper_id": paper_id,
            "gate_passed": False,
            "quality_report": quality_report,
            "skipped_canonical_write": True,
        }

    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        client.upsert_logic_steps_and_claims(paper_id=paper_id, logic=logic_claims["logic"], claims=logic_claims["claims"], step_order=step_order)
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
        # Re-apply human evidence overrides (if any) on top of the rebuilt machine graph.
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
        # Mark rebuild complete
        try:
            client.update_paper_props(
                paper_id,
                {
                    "paper_rebuild_status": "ready",
                    "paper_rebuild_finished_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            )
        except Exception:
            pass

    notify("rebuild:artifacts", 0.86, "Writing rebuilt artifacts to storage")
    out_dir = _storage_dir() / "derived" / "papers" / _safe_id(paper_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "document_ir.json").write_text(
        json.dumps(
            {
                "paper": doc.paper.__dict__,
                "chunks": [{**c.__dict__, "span": c.span.__dict__} for c in doc.chunks],
                "references": [r.__dict__ for r in doc.references],
                "citations": [{**ce.__dict__, "span": ce.span.__dict__} for ce in doc.citations],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "citations.json").write_text(json.dumps(cite_rec, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "llm_imrad.json").write_text(json.dumps(logic_claims, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "llm_citation_purposes.json").write_text(json.dumps(purposes, ensure_ascii=False, indent=2), encoding="utf-8")

    write_log(f"rebuilt artifacts in {out_dir}")
    notify("rebuild:paper_done", 0.92, "Paper rebuild done")
    return {
        "paper_id": paper_id,
        "source_md_path": md_path,
        "reference_recovery": reference_recovery,
        "citation_event_recovery": citation_event_recovery,
        "artifacts_dir": str(out_dir),
        "citations": {
            "refs": len(cite_rec.get("refs") or []),
            "cites_resolved": len(cite_rec.get("cites_resolved") or []),
            "cites_unresolved": len(cite_rec.get("cites_unresolved") or []),
        },
        "llm": {
            "purposes": len(purposes),
            "claims": len(logic_claims.get("claims") or []),
            "gate_passed": bool((logic_claims.get("quality_report") or {}).get("gate_passed")),
            "quality_tier": str((logic_claims.get("quality_report") or {}).get("quality_tier") or ""),
            "quality_report": logic_claims.get("quality_report") or {},
        },
    }


def replace_paper_from_md_path(
    paper_id: str,
    md_path: str,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """
    Replace a paper's subgraph using a specific markdown path (used for DOI-conflict 'Replace with new').
    """
    def notify(stage: str, p: float, msg: str | None = None) -> None:
        if progress:
            progress(stage, p, msg)

    def write_log(line: str) -> None:
        if log:
            log(line)

    md_file = Path(md_path)
    if not md_file.exists():
        raise FileNotFoundError(f"Markdown not found on disk: {md_path}")

    notify("replace:parse", 0.10, "Parsing markdown")
    doc = parse_mineru_markdown(str(md_file))
    schema_for_recovery = _schema_for_md(doc.paper.md_path)
    notify("replace:reference_recovery", 0.18, "Recovering references via fallback agent")
    doc, reference_recovery = recover_references_with_agent(
        doc,
        prompt_overrides=schema_for_recovery.get("prompts"),
        rules=schema_for_recovery.get("rules"),
    )
    notify("replace:citation_event_recovery", 0.22, "Recovering citation events from references when needed")
    doc, citation_event_recovery = recover_citation_events_from_references(
        doc,
        rules=schema_for_recovery.get("rules"),
    )
    citation_event_recovery["paper_source"] = doc.paper.paper_source
    citation_event_recovery["paper_id"] = paper_id_for_md_path(doc.paper.md_path, doi=doc.paper.doi)
    citation_event_recovery["schema_version"] = int(schema_for_recovery.get("version") or 1)
    citation_event_recovery["schema_paper_type"] = str(schema_for_recovery.get("paper_type") or "research")
    expected_paper_id = paper_id_for_md_path(doc.paper.md_path, doi=doc.paper.doi)
    if expected_paper_id != paper_id:
        raise RuntimeError(f"paper_id mismatch: requested={paper_id!r}, parsed={expected_paper_id!r}")

    notify("replace:crossref", 0.25, "Resolving references via Crossref")
    crossref = CrossrefClient()
    # Read crossref_confidence_threshold from schema
    raw_threshold = (schema_for_recovery.get("rules") or {}).get("crossref_confidence_threshold", 0.55)
    try:
        crossref_threshold = float(raw_threshold)
    except Exception:  # noqa: BLE001
        crossref_threshold = 0.55
    crossref_threshold = max(0.0, min(1.0, crossref_threshold))
    cite_rec = build_reference_and_cite_records(doc, crossref=crossref, crossref_confidence_threshold=crossref_threshold)

    notify("replace:neo4j_clear", 0.40, "Clearing existing subgraph for this paper")
    notify("replace:neo4j_write", 0.52, "Writing rebuilt data to Neo4j")
    replace_started_at = datetime.now(tz=timezone.utc).isoformat()
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        client.ensure_schema()
        # Mark rebuild in-progress BEFORE deleting, so a partial rebuild is detectable
        try:
            client.update_paper_props(
                paper_id,
                {"paper_rebuild_status": "rebuilding", "paper_rebuild_started_at": replace_started_at},
            )
        except Exception:
            pass
        client.delete_paper_subgraph(paper_id)
        client.upsert_paper_and_chunks(doc)
        try:
            meta = load_canonical_meta(doc.paper.md_path)
            paper_type = normalize_paper_type(meta.get("paper_type"))
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
            pass
        if cite_rec.get("paper_id"):
            client.upsert_references_and_citations(
                paper_id=cite_rec["paper_id"],
                refs=cite_rec["refs"],
                cited_papers=cite_rec["cited_papers"],
                cites_resolved=cite_rec["cites_resolved"],
                cites_unresolved=cite_rec["cites_unresolved"],
            )

    notify("replace:llm", 0.70, "Running LLM extraction (Logic/Claims/Citation Purposes)")
    schema = _schema_for_md(doc.paper.md_path)
    phase1_artifacts_dir = _storage_dir() / "derived" / "papers" / _safe_id(paper_id) / "raw_pool"
    phase1 = run_phase1_extraction(
        doc=doc,
        paper_id=paper_id,
        cite_rec=cite_rec,
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

    purposes = []
    chunk_by_id = {c.chunk_id: c for c in doc.chunks}
    citing_title = doc.paper.title or doc.paper.title_alt or doc.paper.paper_source
    batch_in = []
    for cr in cite_rec.get("cites_resolved") or []:
        cited_paper_id = cr.get("cited_paper_id")
        cited_doi = None
        if cited_paper_id and str(cited_paper_id).startswith("doi:"):
            cited_doi = str(cited_paper_id)[4:]
        cited_title = None
        for cp in cite_rec.get("cited_papers") or []:
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
    for cr in cite_rec.get("cites_resolved") or []:
        cited_paper_id = cr.get("cited_paper_id")
        if not cited_paper_id:
            continue
        x = by_id.get(str(cited_paper_id)) or {"labels": ["Unknown"], "scores": [0.0]}
        purposes.append({"cited_paper_id": cited_paper_id, "labels": x["labels"], "scores": x["scores"]})

    notify("replace:neo4j_llm", 0.82, "Writing LLM outputs to Neo4j")

    # Phase1 gate: if quality gate failed, skip canonical Claim/LogicStep write.
    quality_report = logic_claims.get("quality_report") or {}
    gate_passed = bool(quality_report.get("gate_passed"))
    if not gate_passed:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            try:
                client.update_paper_props(
                    paper_id,
                    {
                        "paper_rebuild_status": "gate_failed",
                        "phase1_gate_passed": False,
                        "phase1_quality_tier": str(quality_report.get("quality_tier") or ""),
                        "phase1_quality_tier_score": float(quality_report.get("quality_tier_score") or 0.0),
                        "phase1_quality_json": json.dumps(quality_report, ensure_ascii=False),
                    },
                )
            except Exception:
                pass
        notify(
            "replace:gate_failed",
            0.84,
            f"Phase1 gate failed (tier={quality_report.get('quality_tier')}), skipping canonical write",
        )
        write_log(f"gate_failed: paper_id={paper_id} tier={quality_report.get('quality_tier')}")
        return {
            "paper_id": paper_id,
            "source_md_path": md_path,
            "gate_passed": False,
            "quality_report": quality_report,
            "skipped_canonical_write": True,
        }

    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        client.upsert_logic_steps_and_claims(paper_id=paper_id, logic=logic_claims["logic"], claims=logic_claims["claims"], step_order=step_order)
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
        # Mark rebuild complete
        try:
            client.update_paper_props(
                paper_id,
                {
                    "paper_rebuild_status": "ready",
                    "paper_rebuild_finished_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            )
        except Exception:
            pass

    write_log(f"replaced {paper_id} from {md_path}")
    notify("replace:done", 1.0, "Done")
    return {
        "paper_id": paper_id,
        "source_md_path": md_path,
        "reference_recovery": reference_recovery,
        "citation_event_recovery": citation_event_recovery,
        "claims": len(logic_claims.get("claims") or []),
        "gate_passed": bool((logic_claims.get("quality_report") or {}).get("gate_passed")),
        "quality_tier": str((logic_claims.get("quality_report") or {}).get("quality_tier") or ""),
        "quality_report": logic_claims.get("quality_report") or {},
    }


def rebuild_global_faiss(progress: ProgressFn | None = None, log: LogFn | None = None) -> dict[str, Any]:
    def notify(stage: str, p: float, msg: str | None = None) -> None:
        if progress:
            progress(stage, p, msg)

    def write_log(line: str) -> None:
        if log:
            log(line)

    notify("rebuild:faiss_load", 0.10, "Loading chunks from Neo4j")
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        rows = client.list_chunks_for_faiss(limit=200000)
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
                    "evidence_chunk_ids",
                    "evidence_quote",
                ],
            ),
            "communities": (
                build_community_corpus_rows(client, limit=50000),
                [
                    "kind",
                    "source_id",
                    "community_id",
                    "title",
                    "summary",
                    "keyword_texts",
                    "member_ids",
                    "member_kinds",
                ],
            ),
        }

    chunks: list[Chunk] = []
    for r in rows:
        span = MdSpan(start_line=int(r.get("start_line") or 0), end_line=int(r.get("end_line") or 0))
        chunks.append(
            Chunk(
                chunk_id=str(r.get("chunk_id")),
                paper_source=str(r.get("paper_source") or ""),
                md_path=str(r.get("md_path") or ""),
                span=span,
                section=r.get("section"),
                kind=str(r.get("kind") or "block"),
                text=str(r.get("text") or ""),
            )
        )

    if not chunks:
        raise FileNotFoundError("No chunks found in Neo4j (did you ingest anything?)")

    notify("rebuild:faiss_build", 0.55, f"Building FAISS over {len(chunks)} chunks")
    out_dir = _storage_dir() / "faiss"
    cleanup = _clear_stale_legacy_faiss_exports(out_dir)
    if cleanup["removed_corpora"]:
        write_log(f"removed stale FAISS corpora: {', '.join(cleanup['removed_corpora'])}")
    res = {
        "chunks": build_faiss_for_chunks(chunks, out_dir=str(out_dir / "chunks")),
        "corpora": {},
    }
    for corpus, (corpus_rows, metadata_keys) in structured_corpora.items():
        if not corpus_rows:
            continue
        res["corpora"][corpus] = build_faiss_for_rows(
            corpus_rows,
            out_dir=str(out_dir / corpus),
            text_key="text",
            metadata_keys=metadata_keys,
        )
    write_log(f"built global FAISS in {out_dir}")
    notify("rebuild:faiss_done", 1.0, "FAISS rebuild done")
    return {"faiss": res, "dir": str(out_dir), "cleanup": cleanup}
