from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.community.candidate_graph import build_logicstep_candidate_graph
from app.community.labeling import label_community
from app.community.materializer import materialize_community_rows
from app.community.overlap_detection import detect_overlapping_communities
from app.graph.neo4j_client import Neo4jClient
from app.settings import settings


ProgressFn = Callable[[str, float, str | None], None]
LogFn = Callable[[str], None]


def _noop_progress(stage: str, p: float, msg: str | None = None) -> None:
    del stage, p, msg


def _noop_log(line: str) -> None:
    del line


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _build_citation_boost_edges(
    *,
    similar_logic_edges: list[dict[str, Any]],
    logic_steps: list[dict[str, Any]],
    citation_pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not similar_logic_edges or not citation_pairs:
        return []

    paper_by_step = {
        str(row.get('logic_step_id') or '').strip(): str(row.get('paper_id') or '').strip()
        for row in logic_steps
        if str(row.get('logic_step_id') or '').strip()
    }
    citation_pair_set = {
        (
            str(row.get('source_paper_id') or '').strip(),
            str(row.get('target_paper_id') or '').strip(),
        )
        for row in citation_pairs
        if str(row.get('source_paper_id') or '').strip() and str(row.get('target_paper_id') or '').strip()
    }

    boosts: list[dict[str, Any]] = []
    for row in similar_logic_edges:
        source = str(row.get('source') or '').strip()
        target = str(row.get('target') or '').strip()
        if not source or not target:
            continue
        pair = (paper_by_step.get(source, ''), paper_by_step.get(target, ''))
        reverse_pair = (pair[1], pair[0])
        if pair in citation_pair_set or reverse_pair in citation_pair_set:
            boosts.append(
                {
                    'source': source,
                    'target': target,
                    'weight': settings.global_community_v2_citation_boost,
                }
            )
    return boosts


def rebuild_global_communities_v2(
    *,
    client: Neo4jClient | Any | None = None,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    progress = progress or _noop_progress
    log = log or _noop_log

    own_client = client is None
    if own_client:
        client = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
        client.__enter__()

    try:
        client.ensure_schema()
        progress('community:init', 0.05, 'Preparing global community rebuild v2')

        logic_steps = client.list_logic_steps_for_fusion(limit=settings.global_community_max_nodes)
        paper_ids = sorted(
            {
                str(row.get('paper_id') or '').strip()
                for row in logic_steps
                if str(row.get('paper_id') or '').strip()
            }
        )

        progress('community:projection', 0.25, 'Building sparse LogicStep candidate graph')
        similar_logic_edges = client.list_similar_logic_edges_in_papers(
            paper_ids,
            min_score=settings.global_community_v2_similarity_min_score,
            limit_per_source=settings.global_community_v2_neighbor_cap,
            limit_total=settings.global_community_max_edges,
        )
        shared_entity_edges = client.list_shared_entity_logicstep_edges(
            paper_ids,
            limit=settings.global_community_max_edges,
        )
        citation_pairs = client.list_paper_citation_pairs(
            paper_ids,
            limit=settings.global_community_max_edges,
        )
        citation_boosts = _build_citation_boost_edges(
            similar_logic_edges=similar_logic_edges,
            logic_steps=logic_steps,
            citation_pairs=citation_pairs,
        )
        graph = build_logicstep_candidate_graph(
            logic_steps=logic_steps,
            similar_logic_edges=similar_logic_edges,
            shared_entity_edges=shared_entity_edges,
            citation_boosts=citation_boosts,
            neighbor_cap=settings.global_community_v2_neighbor_cap,
        )
        projection_nodes = len(graph['nodes'])
        projection_edges = len(graph['edges'])
        log(f'global community v2 projection: nodes={projection_nodes}, edges={projection_edges}')

        progress('community:cluster', 0.6, 'Running overlapping LogicStep community detection')
        detection = detect_overlapping_communities(
            nodes=list(graph['nodes']),
            edges=list(graph['edges']),
            max_memberships_per_node=settings.global_community_v2_max_memberships_per_node,
            min_community_size=settings.global_community_v2_min_size,
        )

        logic_steps_by_id = {
            str(row.get('logic_step_id') or '').strip(): row
            for row in logic_steps
            if str(row.get('logic_step_id') or '').strip()
        }
        labels: dict[str, dict[str, Any]] = {}
        for community in detection['communities']:
            community_id = str(community.get('community_id') or '').strip()
            core_members = [
                logic_steps_by_id[member_id]
                for member_id in (community.get('core_member_ids') or [])
                if member_id in logic_steps_by_id
            ]
            labels[community_id] = label_community(core_members=core_members, claim_rows=[])

        progress('community:write', 0.85, 'Writing global communities to Neo4j')
        materialized = materialize_community_rows(
            communities=detection['communities'],
            memberships=detection['memberships'],
            labels=labels,
            logic_steps=logic_steps,
            version=settings.global_community_version,
            built_at=_utc_now_iso(),
        )
        cleared = client.clear_global_communities()
        communities_written = client.upsert_global_communities(materialized['communities'])
        keywords_written = client.upsert_global_keywords(materialized['keywords'])
        memberships_written = client.replace_global_memberships(materialized['memberships'])

        progress('community:done', 1.0, 'Global community rebuild v2 complete')
        return {
            'ok': True,
            'projection_nodes': projection_nodes,
            'projection_edges': projection_edges,
            'communities': len(materialized['communities']),
            'keywords': len(materialized['keywords']),
            'communities_written': int(communities_written),
            'keywords_written': int(keywords_written),
            'memberships_written': int(memberships_written),
            'cleared': cleared,
            'version': settings.global_community_version,
        }
    finally:
        if own_client and client is not None:
            client.__exit__(None, None, None)
