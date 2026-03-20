from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any


def _community_score(member_ids: list[str], edge_weight: dict[frozenset[str], float]) -> float:
    if len(member_ids) < 2:
        return 0.0
    scores = [edge_weight.get(frozenset((left, right)), 0.0) for left, right in combinations(member_ids, 2)]
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def detect_overlapping_communities(
    *,
    nodes: list[str],
    edges: list[dict[str, Any]],
    max_memberships_per_node: int = 2,
    min_community_size: int = 2,
) -> dict[str, Any]:
    adjacency: dict[str, dict[str, float]] = defaultdict(dict)
    edge_weight: dict[frozenset[str], float] = {}

    for row in edges:
        source = str(row.get('source') or '').strip()
        target = str(row.get('target') or '').strip()
        if not source or not target or source == target:
            continue
        weight = float(row.get('weight') or 0.0)
        if weight <= 0.0:
            continue
        adjacency[source][target] = max(weight, adjacency[source].get(target, 0.0))
        adjacency[target][source] = max(weight, adjacency[target].get(source, 0.0))
        edge_weight[frozenset((source, target))] = max(weight, edge_weight.get(frozenset((source, target)), 0.0))

    raw_communities: list[dict[str, Any]] = []
    seen_member_sets: set[tuple[str, ...]] = set()
    for source, neighbors in adjacency.items():
        for target, weight in neighbors.items():
            if source >= target:
                continue
            member_ids = tuple(sorted({source, target}))
            if len(member_ids) < min_community_size or member_ids in seen_member_sets:
                continue
            seen_member_sets.add(member_ids)
            raw_communities.append(
                {
                    'community_id': f'gc-v2-{len(raw_communities) + 1}',
                    'member_ids': list(member_ids),
                    'core_member_ids': list(member_ids),
                    'confidence': round(weight, 6),
                }
            )

    raw_communities.sort(key=lambda row: (-float(row['confidence']), row['community_id']))

    memberships: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for community in raw_communities:
        member_ids = list(community['member_ids'])
        community_score = max(float(community.get('confidence') or 0.0), _community_score(member_ids, edge_weight))
        community['confidence'] = round(community_score, 6)
        for member_id in member_ids:
            memberships[member_id].append(
                {
                    'community_id': community['community_id'],
                    'score': round(community_score, 6),
                    'is_core': member_id in set(community.get('core_member_ids') or []),
                }
            )

    trimmed_memberships: dict[str, list[dict[str, Any]]] = {}
    allowed_by_node: dict[str, set[str]] = {}
    safe_cap = max(1, int(max_memberships_per_node))
    for node in nodes:
        node_memberships = sorted(
            memberships.get(node, []),
            key=lambda row: (-float(row['score']), row['community_id']),
        )[:safe_cap]
        for index, row in enumerate(node_memberships, start=1):
            row['rank'] = index
        trimmed_memberships[node] = node_memberships
        allowed_by_node[node] = {str(row['community_id']) for row in node_memberships}

    kept_communities: list[dict[str, Any]] = []
    for community in raw_communities:
        community_id = str(community['community_id'])
        member_ids = [
            member_id
            for member_id in community['member_ids']
            if community_id in allowed_by_node.get(member_id, set())
        ]
        if len(member_ids) < min_community_size:
            continue
        community['member_ids'] = member_ids
        community['member_count'] = len(member_ids)
        community['core_member_ids'] = [
            member_id
            for member_id in community.get('core_member_ids') or []
            if member_id in member_ids
        ]
        kept_communities.append(community)

    surviving_community_ids = {str(row['community_id']) for row in kept_communities}
    for node in list(trimmed_memberships.keys()):
        trimmed_memberships[node] = [
            row
            for row in trimmed_memberships[node]
            if str(row['community_id']) in surviving_community_ids
        ]

    return {
        'communities': kept_communities,
        'memberships': trimmed_memberships,
    }
