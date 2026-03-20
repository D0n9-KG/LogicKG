from __future__ import annotations

from collections import defaultdict
from typing import Any


def build_logicstep_candidate_graph(
    *,
    logic_steps: list[dict[str, Any]],
    similar_logic_edges: list[dict[str, Any]],
    shared_entity_edges: list[dict[str, Any]],
    citation_boosts: list[dict[str, Any]],
    neighbor_cap: int = 32,
) -> dict[str, list[dict[str, Any]] | list[str]]:
    node_ids = [str(row.get('logic_step_id') or '').strip() for row in logic_steps if str(row.get('logic_step_id') or '').strip()]
    paper_by_node = {
        str(row.get('logic_step_id') or '').strip(): str(row.get('paper_id') or '').strip()
        for row in logic_steps
        if str(row.get('logic_step_id') or '').strip()
    }

    edge_scores: dict[tuple[str, str], float] = defaultdict(float)

    def add_edge(source: object, target: object, weight: object) -> None:
        src = str(source or '').strip()
        dst = str(target or '').strip()
        if not src or not dst or src == dst:
            return
        src_paper = paper_by_node.get(src)
        dst_paper = paper_by_node.get(dst)
        if src_paper and dst_paper and src_paper == dst_paper:
            return
        try:
            score = float(weight or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score <= 0.0:
            return
        key = tuple(sorted((src, dst)))
        edge_scores[key] += score

    for row in similar_logic_edges:
        add_edge(row.get('source'), row.get('target'), row.get('score'))
    for row in shared_entity_edges:
        add_edge(row.get('source'), row.get('target'), row.get('score') or row.get('weight') or 0.15)
    for row in citation_boosts:
        add_edge(row.get('source'), row.get('target'), row.get('score') or row.get('weight') or 0.05)

    ranked_edges = sorted(
        (
            {'source': source, 'target': target, 'weight': round(weight, 6)}
            for (source, target), weight in edge_scores.items()
        ),
        key=lambda row: (-float(row['weight']), row['source'], row['target']),
    )

    if neighbor_cap <= 0:
        return {'nodes': node_ids, 'edges': ranked_edges}

    kept_edges: list[dict[str, Any]] = []
    degree_counts: dict[str, int] = defaultdict(int)
    for edge in ranked_edges:
        source = str(edge['source'])
        target = str(edge['target'])
        if degree_counts[source] >= neighbor_cap or degree_counts[target] >= neighbor_cap:
            continue
        kept_edges.append(edge)
        degree_counts[source] += 1
        degree_counts[target] += 1

    return {'nodes': node_ids, 'edges': kept_edges}
