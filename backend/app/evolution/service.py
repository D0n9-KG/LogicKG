from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable

from app.evolution.inference import clamp01, infer_relation_type
from app.graph.neo4j_client import (
    Neo4jClient,
    normalize_proposition_text,
    proposition_id_for_key,
    proposition_key_for_claim,
)
from app.settings import settings


ProgressFn = Callable[[str, float, str | None], None]
LogFn = Callable[[str], None]


_EMBEDDING_MIN_SIMILARITY = 0.85
_DEFAULT_ACCEPT_THRESHOLD = 0.82


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _aggregate_edge_items(events: list[dict], relation_type: str) -> list[dict]:
    rel = str(relation_type or "").upper()
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for e in events:
        if str(e.get("event_type") or "").upper() != rel:
            continue
        if str(e.get("status") or "") != "accepted":
            continue
        source_prop_id = str(e.get("source_prop_id") or "").strip()
        target_prop_id = str(e.get("target_prop_id") or "").strip()
        if not source_prop_id or not target_prop_id or source_prop_id == target_prop_id:
            continue
        key = (source_prop_id, target_prop_id)
        score = clamp01(float(e.get("confidence") or 0.0))
        if key not in agg:
            agg[key] = {"source_prop_id": source_prop_id, "target_prop_id": target_prop_id, "score": score, "evidence_count": 1}
            continue
        item = agg[key]
        item["score"] = max(float(item["score"]), score)
        item["evidence_count"] = int(item["evidence_count"]) + 1
    return list(agg.values())


def _compute_evolution_quality_metrics(
    inferred_events: list[dict],
    supports: list[dict],
    challenges: list[dict],
    supersedes: list[dict],
    total_propositions: int
) -> dict[str, Any]:
    """Compute quality metrics for evolution rebuild.

    Args:
        inferred_events: All inferred events (including non-accepted)
        supports: Aggregated SUPPORTS edges
        challenges: Aggregated CHALLENGES edges
        supersedes: Aggregated SUPERSEDES edges
        total_propositions: Total proposition count from sync

    Returns:
        Dictionary with:
        - coverage_rate: Proportion of propositions with relations
        - covered_propositions: Count of propositions in edges
        - total_propositions: Total proposition count
        - self_loop_rate: Proportion of accepted events that are self-loops
        - self_loop_count: Count of self-loop events
        - total_accepted_events: Count of accepted relation events
    """
    # Collect unique propositions from all edges
    covered_props: set[str] = set()

    for edge in supports + challenges + supersedes:
        source_prop_id = str(edge.get("source_prop_id") or "").strip()
        target_prop_id = str(edge.get("target_prop_id") or "").strip()
        if source_prop_id:
            covered_props.add(source_prop_id)
        if target_prop_id:
            covered_props.add(target_prop_id)

    covered_count = len(covered_props)
    total_props = max(0, int(total_propositions or 0))
    coverage_rate = covered_count / total_props if total_props > 0 else 0.0

    # Count self-loops in accepted inferred events
    # Note: Exclude events with origin="mention" from self-loop counting
    accepted_events = [
        e for e in inferred_events
        if str(e.get("status") or "").strip() == "accepted"
        and str(e.get("origin") or "").strip().lower() != "mention"
    ]

    self_loop_count = 0
    for e in accepted_events:
        source_prop_id = str(e.get("source_prop_id") or "").strip()
        target_prop_id = str(e.get("target_prop_id") or "").strip()
        if source_prop_id and source_prop_id == target_prop_id:
            self_loop_count += 1

    total_accepted = len(accepted_events)
    self_loop_rate = self_loop_count / total_accepted if total_accepted > 0 else 0.0

    return {
        "coverage_rate": coverage_rate,
        "covered_propositions": covered_count,
        "total_propositions": total_props,
        "self_loop_rate": self_loop_rate,
        "self_loop_count": self_loop_count,
        "total_accepted_events": total_accepted,
    }


def _enforce_evolution_quality_gates(metrics: dict[str, Any], settings: Any) -> None:
    """Enforce quality gates for evolution metrics.

    Args:
        metrics: Quality metrics from _compute_evolution_quality_metrics()
        settings: Settings with gate configuration

    Raises:
        ValueError: If quality gates not met
    """
    if not getattr(settings, "evolution_gate_enabled", True):
        return

    min_coverage = float(getattr(settings, "evolution_min_coverage", 0.20))
    max_self_loop_rate = float(getattr(settings, "evolution_max_self_loop_rate", 0.05))

    coverage_rate = float(metrics.get("coverage_rate") or 0.0)
    self_loop_rate = float(metrics.get("self_loop_rate") or 0.0)
    covered_propositions = int(metrics.get("covered_propositions") or 0)
    total_propositions = int(metrics.get("total_propositions") or 0)
    self_loop_count = int(metrics.get("self_loop_count") or 0)
    total_accepted_events = int(metrics.get("total_accepted_events") or 0)

    if coverage_rate < min_coverage:
        raise ValueError(
            "Evolution quality gate failed: coverage rate "
            f"{coverage_rate:.2%} is below minimum {min_coverage:.2%} "
            f"({covered_propositions}/{total_propositions} covered propositions)."
        )

    if self_loop_rate > max_self_loop_rate:
        raise ValueError(
            "Evolution quality gate failed: self-loop rate "
            f"{self_loop_rate:.2%} exceeds maximum {max_self_loop_rate:.2%} "
            f"({self_loop_count}/{total_accepted_events} self-loop accepted events)."
        )


def create_propositions_for_textbook(
    textbook_id: str,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Map eligible KnowledgeEntities to Propositions.

    Only proposition-type entities (theory, equation, method, model,
    condition) are mapped.  Each gets a Proposition node with
    ``source_type='textbook'`` and ``current_state='stable'``.

    The canonical_text is built from ``name + ': ' + description``
    (or just ``name`` if no description).  This ensures the Proposition
    participates in cross-source similarity matching with paper claims.
    """
    progress = progress or (lambda stage, p, msg=None: None)
    log = log or (lambda line: None)

    progress("textbook:propositions:load", 0.02, f"Loading entities for {textbook_id}")
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        entities = client.list_knowledge_entities_for_propositions(textbook_id)

    if not entities:
        log(f"No proposition-eligible entities found for textbook {textbook_id}")
        return {"entities": 0, "propositions": 0}

    log(f"Found {len(entities)} proposition-eligible entities")

    items: list[dict] = []
    for ent in entities:
        name = str(ent.get("name") or "").strip()
        desc = str(ent.get("description") or "").strip()
        etype = str(ent.get("entity_type") or "").strip()
        if not name:
            continue

        # Build canonical text: "name: description" or just "name"
        raw_text = f"{name}: {desc}" if desc else name
        canonical = normalize_proposition_text(raw_text)
        if not canonical:
            continue

        prop_key = proposition_key_for_claim(text=raw_text)
        prop_id = proposition_id_for_key(prop_key)

        items.append({
            "entity_id": str(ent["entity_id"]),
            "prop_id": prop_id,
            "prop_key": prop_key,
            "canonical_text": canonical,
            "source_type": f"textbook:{etype}" if etype else "textbook",
        })

    if not items:
        return {"entities": 0, "propositions": 0}

    progress("textbook:propositions:write", 0.50, f"Creating {len(items)} propositions")
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        stats = client.upsert_proposition_for_entity(items)

    log(f"Textbook propositions created: {stats}")
    progress("textbook:propositions:done", 1.0, "Textbook proposition mapping complete")
    return stats


def sync_proposition_mentions_global(progress: ProgressFn | None = None, log: LogFn | None = None) -> dict[str, Any]:
    progress = progress or (lambda stage, p, msg=None: None)
    log = log or (lambda line: None)

    progress("evolution:sync:init", 0.02, "Loading papers for proposition sync")
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        papers = list(client.list_papers(limit=100000) or [])
        total = len(papers)
        synced_papers = 0
        mapped_claims = 0
        mapped_props: set[str] = set()

        for idx, p in enumerate(papers, start=1):
            paper_id = str(p.get("paper_id") or "").strip()
            if not paper_id:
                continue
            rows = client.list_claim_rows_for_evolution(paper_id=paper_id, limit=10000)
            stats = client.upsert_proposition_mentions_for_claims(paper_id=paper_id, claims=rows, paper_year=p.get("year"))
            synced_papers += 1
            mapped_claims += int(stats.get("claims") or 0)
            for r in rows:
                text = str(r.get("text") or "").strip()
                if not text:
                    continue
                # Use Assertion Layer text-only key (matches neo4j_client.py)
                from app.graph.neo4j_client import proposition_key_for_claim
                prop_key = proposition_key_for_claim(text=text)
                mapped_props.add(prop_key)
            ratio = idx / max(1, total)
            progress("evolution:sync:mentions", 0.02 + ratio * 0.48, f"Synced proposition mentions: {idx}/{total}")

        log(f"evolution sync done: papers={synced_papers} claims={mapped_claims}")
        return {"papers": synced_papers, "claims": mapped_claims, "propositions": len(mapped_props)}


def rebuild_evolution_graph(
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
    *,
    min_similarity: float | None = None,
    candidate_limit: int = 50000,
) -> dict[str, Any]:
    progress = progress or (lambda stage, p, msg=None: None)
    log = log or (lambda line: None)
    built_at = _now_iso()

    progress("evolution:init", 0.01, "Preparing evolution rebuild")
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        client.ensure_schema()

    sync_stats = sync_proposition_mentions_global(progress=progress, log=log)

    progress("evolution:candidates", 0.55, "Loading similarity candidates")
    explicit_min_similarity = clamp01(float(min_similarity)) if min_similarity is not None else None
    similarity_floor = float(explicit_min_similarity) if explicit_min_similarity is not None else _EMBEDDING_MIN_SIMILARITY
    inference_accept_threshold = _DEFAULT_ACCEPT_THRESHOLD

    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        pairs = client.list_proposition_candidate_pairs(min_score=similarity_floor, limit=candidate_limit)

    min_similarity_threshold = float(explicit_min_similarity) if explicit_min_similarity is not None else _EMBEDDING_MIN_SIMILARITY
    raw_max_similarity = 0.0

    inferred_events: list[dict[str, Any]] = []
    for pair in pairs:
        source_prop_id = str(pair.get("source_prop_id") or "").strip()
        target_prop_id = str(pair.get("target_prop_id") or "").strip()
        source_claim_id = str(pair.get("source_claim_id") or "").strip()
        target_claim_id = str(pair.get("target_claim_id") or "").strip()
        if not source_prop_id or not target_prop_id or not source_claim_id or not target_claim_id:
            continue
        if source_prop_id == target_prop_id:
            continue

        raw_similarity = float(pair.get("similarity") or 0.0)
        raw_max_similarity = max(raw_max_similarity, raw_similarity)
        inferred = infer_relation_type(
            source_text=str(pair.get("source_text") or ""),
            target_text=str(pair.get("target_text") or ""),
            similarity=raw_similarity,
            target_confidence=float(pair.get("target_confidence") or 0.5),
            citation_purpose_labels=list(pair.get("citation_purpose_labels") or []),
            citation_purpose_scores=list(pair.get("citation_purpose_scores") or []),
            min_similarity=min_similarity_threshold,
            accepted_threshold=inference_accept_threshold,
        )
        if not inferred:
            continue

        event_type = str(inferred["event_type"])

        # Handle MERGE events separately (text identity - propositions should be merged, not related)
        if event_type == "MERGE":
            # Log merge candidate for post-processing
            log(f"Merge candidate detected: {source_prop_id} <-> {target_prop_id} (text identity)")
            # Skip adding to inferred_events - merges are structural changes, not relations
            continue

        event_seed = f"infer\0{source_claim_id}\0{target_claim_id}\0{event_type}"
        event_id = hashlib.sha256(event_seed.encode("utf-8", errors="ignore")).hexdigest()[:32]
        inferred_events.append(
            {
                "event_id": event_id,
                "event_type": event_type,
                "status": str(inferred["status"]),
                "confidence": clamp01(float(inferred["confidence"])),
                "strength": clamp01(float(inferred["strength"])),
                "source_prop_id": source_prop_id,
                "target_prop_id": target_prop_id,
                "source_claim_id": source_claim_id,
                "target_claim_id": target_claim_id,
                "source_paper_id": str(pair.get("source_paper_id") or ""),
                "target_paper_id": str(pair.get("target_paper_id") or ""),
                "raw_similarity": raw_similarity,
                "normalized_similarity": raw_similarity,
                "inference_version": "v1",
                "event_time": built_at,
            }
        )

    progress("evolution:write", 0.72, "Writing inferred events and relation edges")
    supports = _aggregate_edge_items(inferred_events, "SUPPORTS")
    challenges = _aggregate_edge_items(inferred_events, "CHALLENGES")
    supersedes = _aggregate_edge_items(inferred_events, "SUPERSEDES")

    # P0-6: Compute quality metrics and enforce gates
    quality_metrics = _compute_evolution_quality_metrics(
        inferred_events=inferred_events,
        supports=supports,
        challenges=challenges,
        supersedes=supersedes,
        total_propositions=int(sync_stats.get("propositions") or 0),
    )

    log(
        "evolution_quality: "
        f"coverage={quality_metrics['coverage_rate']:.1%} "
        f"({quality_metrics['covered_propositions']}/{quality_metrics['total_propositions']}) "
        f"self_loop={quality_metrics['self_loop_rate']:.1%} "
        f"({quality_metrics['self_loop_count']}/{quality_metrics['total_accepted_events']})"
    )

    # Enforce quality gates (raises ValueError if failed)
    _enforce_evolution_quality_gates(quality_metrics, settings)

    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        client.replace_inferred_relation_events(inferred_events, built_at=built_at)
        client.replace_proposition_support_edges(supports, built_at=built_at)
        client.replace_proposition_challenge_edges(challenges, built_at=built_at)
        client.replace_proposition_supersede_edges(supersedes, built_at=built_at)
        state_stats = client.recompute_proposition_states()

    progress("evolution:done", 1.0, "Evolution rebuild completed")
    log(
        "evolution rebuilt: "
        f"events={len(inferred_events)} "
        f"supports={len(supports)} challenges={len(challenges)} supersedes={len(supersedes)}"
    )
    return {
        "ok": True,
        "built_at": built_at,
        "sync": sync_stats,
        "candidates": len(pairs),
        "similarity": {
            "pair_similarity_floor": similarity_floor,
            "pair_raw_max_similarity": raw_max_similarity,
            "inference_accept_threshold": inference_accept_threshold,
            "embedding_min_similarity": _EMBEDDING_MIN_SIMILARITY,
            "override_min_similarity": explicit_min_similarity,
        },
        "events": len(inferred_events),
        "edges": {
            "supports": len(supports),
            "challenges": len(challenges),
            "supersedes": len(supersedes),
        },
        "quality_metrics": quality_metrics,
        "states": state_stats,
    }
