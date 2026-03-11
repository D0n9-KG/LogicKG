from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import uuid

from app.discovery.context_builder import build_hybrid_context_for_gap
from app.discovery.evidence_auditor import audit_candidate_evidence
from app.discovery.gap_detector import detect_knowledge_gaps
from app.discovery.models import ResearchQuestionCandidate
from app.discovery.prompt_policy import update_policy_from_candidates
from app.discovery.question_generator import generate_candidate_questions
from app.discovery.ranker import rank_candidates
from app.graph.neo4j_client import Neo4jClient
from app.settings import settings


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


def _attach_hybrid_context(
    *,
    domain: str,
    dry_run: bool,
    gaps: list[dict],
    candidates: list[dict],
    hop_order: int,
    adjacent_samples: int,
    random_samples: int,
    rag_top_k: int,
    community_method: str,
    community_samples: int,
) -> list[dict]:
    if not candidates:
        return []

    gap_by_id = {str(g.get("gap_id") or "").strip(): dict(g) for g in (gaps or []) if str(g.get("gap_id") or "").strip()}
    out: list[dict] = []
    for raw in candidates:
        row = dict(raw or {})
        gap_id = str(row.get("gap_id") or "").strip()
        gap = dict(gap_by_id.get(gap_id) or {})
        if not gap and gap_id:
            gap = {"gap_id": gap_id, "description": str(row.get("question") or "")}
        try:
            ctx = build_hybrid_context_for_gap(
                domain=domain,
                gap=gap,
                question=str(row.get("question") or ""),
                hop_order=hop_order,
                adjacent_samples=adjacent_samples,
                random_samples=random_samples,
                rag_top_k=rag_top_k,
                community_method=community_method,
                community_samples=community_samples,
                dry_run=dry_run,
            )
        except Exception:
            ctx = {}

        existing_source_papers = [str(x) for x in (row.get("source_paper_ids") or [])]
        ctx_source_papers = [str(x) for x in (ctx.get("source_paper_ids") or [])]
        row["source_paper_ids"] = _dedup(existing_source_papers + ctx_source_papers)
        row["inspiration_adjacent_paper_ids"] = _dedup([str(x) for x in (ctx.get("inspiration_adjacent_paper_ids") or [])])
        row["inspiration_random_paper_ids"] = _dedup([str(x) for x in (ctx.get("inspiration_random_paper_ids") or [])])
        row["inspiration_community_paper_ids"] = _dedup([str(x) for x in (ctx.get("inspiration_community_paper_ids") or [])])

        graph_summary = str(ctx.get("graph_context_summary") or "").strip()
        if graph_summary:
            row["graph_context_summary"] = graph_summary

        rag_snippets = _dedup([str(x) for x in (ctx.get("rag_context_snippets") or [])])
        if rag_snippets:
            merged_snips = _dedup([str(x) for x in (row.get("rag_context_snippets") or [])] + rag_snippets)
            row["rag_context_snippets"] = merged_snips[:8]

        out.append(row)
    return out


def _persist_discovery_graph(
    *,
    domain: str,
    batch_id: str,
    gaps: list[dict],
    candidates: list[dict],
    built_at: str,
) -> bool:
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.upsert_discovery_graph(
                domain=domain,
                batch_id=batch_id,
                gaps=gaps,
                questions=candidates,
                built_at=built_at,
            )
        return True
    except Exception:
        return False


def run_discovery_batch(
    domain: str,
    dry_run: bool = False,
    *,
    max_gaps: int = 8,
    candidates_per_gap: int = 2,
    use_llm: bool | None = None,
    hop_order: int = 2,
    adjacent_samples: int = 6,
    random_samples: int = 2,
    rag_top_k: int = 4,
    prompt_optimize: bool = True,
    community_method: str = "hybrid",
    community_samples: int = 4,
    prompt_optimization_method: str = "rl_bandit",
) -> dict:
    final_max_gaps = max(1, min(64, int(max_gaps)))
    final_cpg = max(1, min(3, int(candidates_per_gap)))
    llm_enabled = bool(use_llm) if use_llm is not None else (not dry_run)
    final_hops = max(1, min(3, int(hop_order)))
    final_adj = max(0, min(30, int(adjacent_samples)))
    final_rand = max(0, min(30, int(random_samples)))
    final_rag_top_k = max(1, min(8, int(rag_top_k)))
    final_prompt_opt = bool(prompt_optimize)
    method = str(community_method or "hybrid").strip().lower()
    if method not in {"author_hop", "louvain", "hybrid"}:
        method = "hybrid"
    final_community_samples = max(0, min(30, int(community_samples)))
    prompt_method = str(prompt_optimization_method or "rl_bandit").strip().lower()
    if prompt_method not in {"rl_bandit", "heuristic"}:
        prompt_method = "rl_bandit"
    batch_id = f"dbatch:{uuid.uuid4().hex[:12]}"
    built_at = datetime.now(tz=timezone.utc).isoformat()

    gaps = detect_knowledge_gaps(domain=domain, limit=final_max_gaps)
    generated = generate_candidate_questions(
        gaps,
        domain=str(domain or "default"),
        candidates_per_gap=final_cpg,
        use_llm=llm_enabled,
        optimize_prompt=final_prompt_opt,
        prompt_optimization_method=prompt_method,
    )
    generated = _attach_hybrid_context(
        domain=str(domain),
        dry_run=bool(dry_run),
        gaps=gaps,
        candidates=generated,
        hop_order=final_hops,
        adjacent_samples=final_adj,
        random_samples=final_rand,
        rag_top_k=final_rag_top_k,
        community_method=method,
        community_samples=final_community_samples,
    )

    audited: list[dict] = []
    for candidate in generated:
        row = audit_candidate_evidence(candidate, dry_run=dry_run)
        support = row.get("support_evidence_ids") or []
        if support:
            # Validate schema only when support evidence exists.
            model = ResearchQuestionCandidate(
                candidate_id=str(row.get("candidate_id") or ""),
                question=str(row.get("question") or ""),
                gap_id=row.get("gap_id"),
                gap_type=str(row.get("gap_type") or "seed"),
                motivation=row.get("motivation"),
                novelty=row.get("novelty"),
                proposed_method=row.get("proposed_method"),
                difference=row.get("difference"),
                feasibility=row.get("feasibility"),
                risk_statement=row.get("risk_statement"),
                evaluation_metrics=list(row.get("evaluation_metrics") or []),
                timeline=row.get("timeline"),
                source_claim_ids=list(row.get("source_claim_ids") or []),
                source_community_ids=list(row.get("source_community_ids") or []),
                source_paper_ids=list(row.get("source_paper_ids") or []),
                inspiration_adjacent_paper_ids=list(row.get("inspiration_adjacent_paper_ids") or []),
                inspiration_random_paper_ids=list(row.get("inspiration_random_paper_ids") or []),
                inspiration_community_paper_ids=list(row.get("inspiration_community_paper_ids") or []),
                graph_context_summary=row.get("graph_context_summary"),
                rag_context_snippets=list(row.get("rag_context_snippets") or []),
                generation_mode=str(row.get("generation_mode") or "template"),
                prompt_variant=row.get("prompt_variant"),
                generation_confidence=float(row.get("generation_confidence") or 0.0),
                optimization_score=float(row.get("optimization_score") or 0.0),
                novelty_score=float(row.get("novelty_score") or 0.0),
                feasibility_score=float(row.get("feasibility_score") or 0.0),
                relevance_score=float(row.get("relevance_score") or 0.0),
                support_coverage=float(row.get("support_coverage") or 0.0),
                challenge_coverage=float(row.get("challenge_coverage") or 0.0),
                support_evidence_ids=list(support),
                challenge_evidence_ids=list(row.get("challenge_evidence_ids") or []),
                missing_evidence_statement=row.get("missing_evidence_statement"),
                quality_score=float(row.get("quality_score") or 0.0),
                status=str(row.get("status") or "ranked"),
            )
            row.update(model.model_dump())
        audited.append(row)

    ranked = rank_candidates(audited)
    policy_updates = update_policy_from_candidates(domain=str(domain), candidates=ranked, source="batch")
    needs_more = sum(1 for c in ranked if str(c.get("status") or "") == "needs_more_evidence")
    accepted = sum(1 for c in ranked if str(c.get("status") or "") == "accepted")
    with_hybrid = sum(1 for c in ranked if str(c.get("graph_context_summary") or "").strip())
    total_adjacent = sum(len(list(c.get("inspiration_adjacent_paper_ids") or [])) for c in ranked)
    total_random = sum(len(list(c.get("inspiration_random_paper_ids") or [])) for c in ranked)
    total_community = sum(len(list(c.get("inspiration_community_paper_ids") or [])) for c in ranked)
    gap_types = Counter(str(g.get("gap_type") or "seed") for g in gaps)
    graph_persisted = _persist_discovery_graph(
        domain=str(domain),
        batch_id=batch_id,
        gaps=gaps,
        candidates=ranked,
        built_at=built_at,
    )

    return {
        "domain": str(domain),
        "batch_id": batch_id,
        "built_at": built_at,
        "dry_run": bool(dry_run),
        "graph_persisted": graph_persisted,
        "settings": {
            "max_gaps": final_max_gaps,
            "candidates_per_gap": final_cpg,
            "use_llm": llm_enabled,
            "hop_order": final_hops,
            "adjacent_samples": final_adj,
            "random_samples": final_rand,
            "rag_top_k": final_rag_top_k,
            "prompt_optimize": final_prompt_opt,
            "community_method": method,
            "community_samples": final_community_samples,
            "prompt_optimization_method": prompt_method,
        },
        "gaps": gaps,
        "candidates": ranked,
        "summary": {
            "gap_count": len(gaps),
            "candidate_count": len(ranked),
            "needs_more_evidence_count": needs_more,
            "accepted_count": accepted,
            "gap_type_counts": dict(gap_types),
            "hybrid_context_count": with_hybrid,
            "inspiration_adjacent_papers_total": total_adjacent,
            "inspiration_random_papers_total": total_random,
            "inspiration_community_papers_total": total_community,
            "prompt_policy_updates": policy_updates,
        },
    }
