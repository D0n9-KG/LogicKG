from __future__ import annotations

import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from app.crossref.client import CrossrefClient, CrossrefResolveResult
from app.graph.neo4j_client import paper_id_for_md_path
from app.ingest.models import DocumentIR, ReferenceEntry

logger = logging.getLogger(__name__)


def _crossref_workers(crossref: CrossrefClient, item_count: int) -> int:
    try:
        workers = int(crossref.recommended_workers())
    except Exception:  # noqa: BLE001
        workers = 1
    return max(1, min(workers, max(1, int(item_count))))


def build_reference_and_cite_records(
    doc: DocumentIR,
    crossref: CrossrefClient,
    crossref_confidence_threshold: float = 0.55,
    max_evidence: int = 5,
) -> dict:
    """
    Produce JSON-serializable records for Neo4j:
    - ReferenceEntry nodes for every ref entry
    - (Paper)-[:CITES]->(Paper) edges when DOI resolved with enough confidence
    - (Paper)-[:CITES_UNRESOLVED]->(ReferenceEntry) edges otherwise

    Note: Neo4j relationship properties cannot store maps; we use arrays and JSON strings.
    """

    paper_id = paper_id_for_md_path(doc.paper.md_path, doi=doc.paper.doi)

    ref_by_num: dict[int, ReferenceEntry] = {}
    for ref in doc.references:
        if ref.ref_num in ref_by_num:
            logger.warning(
                "Duplicate ref_num %d in paper %s (paper_source=%r): "
                "keeping first occurrence, skipping subsequent.",
                ref.ref_num,
                paper_id,
                doc.paper.paper_source,
            )
            continue
        ref_by_num[ref.ref_num] = ref
    cite_events_by_ref: dict[int, list] = defaultdict(list)
    for ce in doc.citations:
        cite_events_by_ref[ce.cited_ref_num].append(ce)

    refs_out: list[dict] = []
    cited_papers_out: dict[str, dict] = {}
    cites_resolved_by_doi: dict[str, dict] = {}
    cites_unresolved: list[dict] = []

    def _resolve_one(ref_num: int, ref: ReferenceEntry) -> tuple[int, dict]:
        crossref_error: str | None = None
        try:
            resolve = crossref.resolve_reference(ref.raw)
        except Exception as exc:  # noqa: BLE001
            crossref_error = str(exc)
            resolve = CrossrefResolveResult(query=ref.raw, topk=[], selected=None, confidence=0.0)
        selected = resolve.selected
        crossref_json = crossref.dumps(resolve)
        if crossref_error:
            try:
                payload = json.loads(crossref_json)
                if not isinstance(payload, dict):
                    payload = {"query": ref.raw}
            except Exception:  # noqa: BLE001
                payload = {"query": ref.raw}
            payload["error"] = crossref_error
            crossref_json = json.dumps(payload, ensure_ascii=False)

        return ref_num, {
            "selected": selected,
            "confidence": resolve.confidence,
            "crossref_json": crossref_json,
            "crossref_error": crossref_error,
        }

    ref_items = sorted(ref_by_num.items(), key=lambda x: x[0])
    resolved_refs: dict[int, dict] = {}
    workers = _crossref_workers(crossref, len(ref_items))
    if workers == 1 or len(ref_items) <= 1:
        for ref_num, ref in ref_items:
            resolved_ref_num, payload = _resolve_one(ref_num, ref)
            resolved_refs[resolved_ref_num] = payload
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_resolve_one, ref_num, ref) for ref_num, ref in ref_items]
            for future in futures:
                resolved_ref_num, payload = future.result()
                resolved_refs[resolved_ref_num] = payload

    for ref_num, ref in ref_items:
        resolved = resolved_refs[ref_num]
        selected = resolved["selected"]
        crossref_json = str(resolved["crossref_json"])
        crossref_error = resolved["crossref_error"]

        ref_id = f"{paper_id}:{ref_num}"
        refs_out.append(
            {
                "ref_id": ref_id,
                "paper_id": paper_id,
                "ref_num": ref_num,
                "raw": ref.raw,
                "resolved_doi": selected.doi if selected else None,
                "resolve_confidence": resolved["confidence"],
                "crossref_json": crossref_json,
                "crossref_error": crossref_error,
                "resolved_title": selected.title if selected else None,
                "resolved_year": selected.year if selected else None,
                "resolved_venue": selected.venue if selected else None,
                "resolved_authors": selected.authors if selected else [],
            }
        )

        events = cite_events_by_ref.get(ref_num, [])
        if not events:
            continue

        evidence_chunk_ids: list[str] = []
        evidence_spans: list[str] = []
        for e in events[:max_evidence]:
            evidence_chunk_ids.append(e.chunk_id)
            evidence_spans.append(f"{e.span.start_line}-{e.span.end_line}")

        if selected and selected.doi and float(resolved["confidence"]) >= crossref_confidence_threshold:
            doi = selected.doi.lower()
            cited_paper_id = f"doi:{doi}"
            cited_papers_out.setdefault(
                cited_paper_id,
                {
                    "paper_id": cited_paper_id,
                    "doi": doi,
                    "title": selected.title,
                    "year": selected.year,
                    "venue": selected.venue,
                    "authors": selected.authors,
                },
            )

            if doi not in cites_resolved_by_doi:
                cites_resolved_by_doi[doi] = {
                    "cited_paper_id": cited_paper_id,
                    "total_mentions": 0,
                    "ref_nums": [],
                    "evidence_chunk_ids": [],
                    "evidence_spans": [],
                }
            rec = cites_resolved_by_doi[doi]
            rec["total_mentions"] += len(events)
            if ref_num not in rec["ref_nums"]:
                rec["ref_nums"].append(ref_num)
            rec["evidence_chunk_ids"] = (rec["evidence_chunk_ids"] + evidence_chunk_ids)[:max_evidence]
            rec["evidence_spans"] = (rec["evidence_spans"] + evidence_spans)[:max_evidence]
        else:
            cites_unresolved.append(
                {
                    "ref_id": ref_id,
                    "total_mentions": len(events),
                    "ref_nums": [ref_num],
                    "evidence_chunk_ids": evidence_chunk_ids,
                    "evidence_spans": evidence_spans,
                }
            )

    return {
        "paper_id": paper_id,
        "refs": refs_out,
        "cited_papers": list(cited_papers_out.values()),
        "cites_resolved": list(cites_resolved_by_doi.values()),
        "cites_unresolved": cites_unresolved,
    }
