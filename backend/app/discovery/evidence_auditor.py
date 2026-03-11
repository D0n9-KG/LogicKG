from __future__ import annotations

from pathlib import Path
from typing import Any

from app.graph.neo4j_client import Neo4jClient
from app.rag.retrieval import latest_run_dir, lexical_retrieve, load_chunks_from_run
from app.settings import settings


_CHUNK_CACHE: dict[str, list[dict[str, Any]]] = {}


def _clamp01(v: float) -> float:
    if v <= 0:
        return 0.0
    if v >= 1:
        return 1.0
    return float(v)


def _runs_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runs"


def _load_chunks_cached() -> list[dict[str, Any]]:
    try:
        run_dir = latest_run_dir(_runs_dir())
    except Exception:
        return []
    key = str(run_dir)
    cached = _CHUNK_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        chunks = load_chunks_from_run(run_dir)
    except Exception:
        chunks = []
    _CHUNK_CACHE.clear()
    _CHUNK_CACHE[key] = chunks
    return chunks


def _dedup_ids(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _collect_lexical_chunk_evidence(
    question: str,
    k: int = 3,
    *,
    allowed_paper_sources: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    chunks = _load_chunks_cached()
    if not chunks:
        return [], []
    hits = lexical_retrieve(question, chunks, k=max(1, min(8, int(k))))
    evidence_ids: list[str] = []
    snippets: list[str] = []
    for hit in hits:
        if allowed_paper_sources and str(hit.paper_source or "").strip() not in allowed_paper_sources:
            continue
        evidence_ids.append(f"CH:{hit.chunk_id}")
        snippet = str(hit.snippet or "").strip()
        if snippet:
            snippets.append(snippet[:220])
        if len(evidence_ids) >= max(1, min(8, int(k))):
            break

    if not evidence_ids and allowed_paper_sources:
        # scoped retrieval fallback to global lexical hits
        for hit in hits[: max(1, min(8, int(k)))]:
            evidence_ids.append(f"CH:{hit.chunk_id}")
            snippet = str(hit.snippet or "").strip()
            if snippet:
                snippets.append(snippet[:220])
    return _dedup_ids(evidence_ids), snippets[:3]


def _paper_sources_for_ids(paper_ids: list[str]) -> set[str]:
    ids = _dedup_ids([str(x) for x in (paper_ids or [])])
    if not ids:
        return set()
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            rows = client.list_papers_by_ids(ids, limit=500)
    except Exception:
        return set()
    out: set[str] = set()
    for row in rows:
        paper_source = str(row.get("paper_source") or "").strip()
        if paper_source:
            out.add(paper_source)
    return out


def _collect_community_member_claim_ids(community_ids: list[str], max_items: int = 4) -> list[str]:
    ids: list[str] = []
    if not community_ids:
        return ids
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            for community_id in community_ids[:3]:
                members = client.list_global_community_members(community_id, limit=200)
                for member in members:
                    member_id = str(member.get("member_id") or "").strip()
                    member_kind = str(member.get("member_kind") or "").strip().lower()
                    if not member_id or member_kind != "claim":
                        continue
                    ids.append(member_id)
                    if len(ids) >= max_items:
                        return _dedup_ids(ids)
    except Exception:
        return []
    return _dedup_ids(ids)


def audit_candidate_evidence(candidate: dict, *, dry_run: bool = False) -> dict:
    """Attach real support/challenge evidence and quality score."""
    base = dict(candidate or {})
    question = str(base.get("question") or "").strip()

    support_ids = _dedup_ids([str(x) for x in (base.get("support_evidence_ids") or [])])
    challenge_ids = _dedup_ids([str(x) for x in (base.get("challenge_evidence_ids") or [])])
    source_claim_ids = _dedup_ids([str(x) for x in (base.get("source_claim_ids") or [])])
    source_community_ids = _dedup_ids([str(x) for x in (base.get("source_community_ids") or [])])
    source_paper_ids = _dedup_ids([str(x) for x in (base.get("source_paper_ids") or [])])

    if dry_run and question:
        support_ids.extend([f"E:{base.get('candidate_id', 'rq')}:support:1"])
        if "temperature" in question.lower() or "conflict" in question.lower():
            challenge_ids.extend([f"E:{base.get('candidate_id', 'rq')}:challenge:1"])
        base["rag_context_snippets"] = list(base.get("rag_context_snippets") or [])
    else:
        # 1) Reuse provenance from upstream graph mining.
        support_ids.extend([f"CL:{cid}" for cid in source_claim_ids[:4]])
        support_ids.extend([f"GC:{cid}" for cid in source_community_ids[:3]])
        support_ids.extend([f"CL:{cid}" for cid in _collect_community_member_claim_ids(source_community_ids, max_items=4)])

        # 2) Retrieve chunk-level lexical evidence for better grounding.
        paper_sources = _paper_sources_for_ids(source_paper_ids)
        lexical_ids, lexical_snippets = _collect_lexical_chunk_evidence(
            question,
            k=3,
            allowed_paper_sources=paper_sources or None,
        )
        support_ids.extend(lexical_ids)
        rag_snips = [str(x) for x in (base.get("rag_context_snippets") or [])]
        rag_snips.extend(lexical_snippets)
        base["rag_context_snippets"] = _dedup_ids(rag_snips)[:4]

    support_ids = _dedup_ids(support_ids)
    challenge_ids = _dedup_ids(challenge_ids)

    support_coverage = _clamp01(len(support_ids) / 3.0)
    challenge_coverage = _clamp01(len(challenge_ids) / 2.0)
    novelty = _clamp01(float(base.get("novelty_score") or 0.0))
    feasibility = _clamp01(float(base.get("feasibility_score") or 0.0))
    relevance = _clamp01(float(base.get("relevance_score") or 0.0))

    quality_score = (
        0.45 * support_coverage
        + 0.15 * challenge_coverage
        + 0.20 * novelty
        + 0.10 * feasibility
        + 0.10 * relevance
    )

    needs_more_evidence = len(support_ids) < 1 or (not dry_run and len(support_ids) < 2)
    if needs_more_evidence:
        quality_score *= 0.7

    base["support_evidence_ids"] = support_ids
    base["challenge_evidence_ids"] = challenge_ids
    base["support_coverage"] = support_coverage
    base["challenge_coverage"] = challenge_coverage
    base["quality_score"] = float(round(max(0.0, quality_score), 4))
    base["status"] = "needs_more_evidence" if needs_more_evidence else "ranked"

    if needs_more_evidence and not str(base.get("missing_evidence_statement") or "").strip():
        base["missing_evidence_statement"] = (
            "Needs additional support evidence from at least two independent signals "
            "(claim/community/chunk) before ranking."
        )
    return base
