from __future__ import annotations

from pathlib import Path
from typing import Any

from app.graph.neo4j_client import Neo4jClient
from app.rag.retrieval import latest_run_dir, lexical_retrieve, load_chunks_from_run
from app.settings import settings


_CHUNK_CACHE: dict[str, list[dict[str, Any]]] = {}


def _runs_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runs"


def _norm(text: str, *, limit: int = 240) -> str:
    merged = " ".join(str(text or "").split()).strip()
    if len(merged) <= limit:
        return merged
    return merged[: limit - 3].rstrip() + "..."


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


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


def _pick_target_paper_ids(client: Neo4jClient, gap: dict) -> list[str]:
    out = _dedup([str(x) for x in (gap.get("source_paper_ids") or [])])
    if out:
        return out

    claim_ids = _dedup([str(x) for x in (gap.get("source_claim_ids") or [])])
    if claim_ids:
        out.extend(client.list_paper_ids_for_claims(claim_ids, limit=80))
        out = _dedup(out)
    if out:
        return out

    prop_ids = _dedup([str(x) for x in (gap.get("source_proposition_ids") or [])])
    if prop_ids:
        out.extend(client.list_paper_ids_for_propositions(prop_ids, limit=80))
        out = _dedup(out)
    return out


def _build_graph_summary(
    *,
    gap: dict,
    paper_rows: list[dict],
    citation_context: list[dict],
    structured: dict[str, list[dict]],
    adjacent_count: int,
    random_count: int,
    community_count: int,
) -> str:
    paper_titles = [_norm(str(x.get("title") or ""), limit=88) for x in paper_rows if str(x.get("title") or "").strip()]
    paper_titles = [x for x in paper_titles if x]

    cited_titles = []
    for row in citation_context[:8]:
        cited = _norm(str(row.get("cited_title") or ""), limit=72)
        if cited:
            cited_titles.append(cited)

    claim_texts = []
    for row in (structured.get("claims") or [])[:4]:
        text = _norm(str(row.get("text") or ""), limit=110)
        if text:
            claim_texts.append(text)

    step_types = []
    for row in (structured.get("logic_steps") or [])[:6]:
        st = str(row.get("step_type") or "").strip()
        if st:
            step_types.append(st)
    step_types = _dedup(step_types)

    gap_desc = _norm(str(gap.get("description") or ""), limit=140)
    lines = [
        f"Gap focus: {gap_desc}" if gap_desc else "Gap focus: unresolved cross-paper mechanism",
        f"Inspiration sampling: adjacent={adjacent_count}, community={community_count}, random={random_count}",
    ]
    if paper_titles:
        lines.append("Core papers: " + "; ".join(paper_titles[:5]))
    if cited_titles:
        lines.append("Citation adjacencies: " + "; ".join(_dedup(cited_titles)[:5]))
    if step_types:
        lines.append("Dominant logic steps: " + ", ".join(step_types[:5]))
    if claim_texts:
        lines.append("Evidence motifs: " + "; ".join(claim_texts[:3]))
    return _norm("\n".join(lines), limit=1200)


def _retrieve_rag_snippets(query: str, *, paper_sources: set[str], rag_top_k: int) -> list[str]:
    chunks = _load_chunks_cached()
    if not chunks:
        return []

    k = max(1, min(8, int(rag_top_k)))
    candidates = lexical_retrieve(query, chunks, k=max(8, k * 4))
    picked: list[str] = []
    for hit in candidates:
        if paper_sources and str(hit.paper_source or "").strip() not in paper_sources:
            continue
        text = _norm(str(hit.snippet or ""), limit=280)
        if text:
            picked.append(text)
        if len(picked) >= k:
            break

    # fallback: when scoped retrieval is empty, back off to global lexical snippets
    if not picked:
        for hit in candidates[:k]:
            text = _norm(str(hit.snippet or ""), limit=280)
            if text:
                picked.append(text)

    return _dedup(picked)[:k]


def build_hybrid_context_for_gap(
    *,
    domain: str,
    gap: dict,
    question: str | None = None,
    hop_order: int = 2,
    adjacent_samples: int = 6,
    random_samples: int = 2,
    rag_top_k: int = 4,
    community_method: str = "hybrid",
    community_samples: int = 4,
    dry_run: bool = False,
) -> dict:
    """Build a GYWI-style hybrid context (author-hop inspiration + RAG snippets + graph summary)."""
    gap_row = dict(gap or {})
    if dry_run:
        seed = _norm(str(gap_row.get("description") or ""), limit=120)
        return {
            "graph_context_summary": _norm(
                f"Gap focus: {seed or 'unresolved mechanism'}\n"
                f"Inspiration sampling: adjacent={max(0, int(adjacent_samples))}, community={max(0, int(community_samples))}, random={max(0, int(random_samples))}",
                limit=800,
            ),
            "rag_context_snippets": [str(gap_row.get("missing_evidence_statement") or "").strip()] if str(gap_row.get("missing_evidence_statement") or "").strip() else [],
            "source_paper_ids": _dedup([str(x) for x in (gap_row.get("source_paper_ids") or [])]),
            "inspiration_adjacent_paper_ids": [],
            "inspiration_community_paper_ids": [],
            "inspiration_random_paper_ids": [],
        }

    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            target_ids = _pick_target_paper_ids(client, gap_row)
            sampled = client.sample_inspiration_papers(
                target_paper_ids=target_ids,
                hop_order=hop_order,
                adjacent_samples=adjacent_samples,
                random_samples=random_samples,
                community_method=community_method,
                community_samples=community_samples,
            )
            adjacent_rows = list(sampled.get("adjacent_papers") or [])
            community_rows = list(sampled.get("community_papers") or [])
            random_rows = list(sampled.get("random_papers") or [])
            adjacent_ids = _dedup([str(r.get("paper_id") or "") for r in adjacent_rows])
            community_ids = _dedup([str(r.get("paper_id") or "") for r in community_rows])
            random_ids = _dedup([str(r.get("paper_id") or "") for r in random_rows])

            all_ids = _dedup([*target_ids, *adjacent_ids, *community_ids, *random_ids])
            paper_rows = client.list_papers_by_ids(all_ids, limit=300) if all_ids else []
            paper_sources = {
                str(r.get("paper_source") or "").strip()
                for r in paper_rows
                if str(r.get("paper_source") or "").strip()
            }

            citation_context = client.get_citation_context_by_paper_source(sorted(paper_sources), limit=60) if paper_sources else []
            structured = client.get_structured_knowledge_for_papers(sorted(paper_sources), max_claims=18, max_steps=10) if paper_sources else {"claims": [], "logic_steps": []}
    except Exception:
        return {
            "graph_context_summary": "",
            "rag_context_snippets": [],
            "source_paper_ids": _dedup([str(x) for x in (gap_row.get("source_paper_ids") or [])]),
            "inspiration_adjacent_paper_ids": [],
            "inspiration_community_paper_ids": [],
            "inspiration_random_paper_ids": [],
        }

    query = _norm(question or str(gap_row.get("description") or "") or str(gap_row.get("title") or ""), limit=200)
    rag_snippets = _retrieve_rag_snippets(query, paper_sources=paper_sources, rag_top_k=rag_top_k)
    graph_summary = _build_graph_summary(
        gap=gap_row,
        paper_rows=paper_rows,
        citation_context=citation_context,
        structured=structured,
        adjacent_count=len(adjacent_rows),
        random_count=len(random_rows),
        community_count=len(community_rows),
    )

    return {
        "graph_context_summary": graph_summary,
        "rag_context_snippets": rag_snippets,
        "source_paper_ids": _dedup([*(_dedup([str(x) for x in (gap_row.get("source_paper_ids") or [])])), *[str(x) for x in adjacent_ids], *[str(x) for x in community_ids], *[str(x) for x in random_ids]]),
        "inspiration_adjacent_paper_ids": adjacent_ids,
        "inspiration_community_paper_ids": community_ids,
        "inspiration_random_paper_ids": random_ids,
    }
