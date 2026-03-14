from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-+/]*")
_MEMBER_KIND_PRIORITY = {
    "claim": 0,
    "logicstep": 1,
    "logic_step": 1,
    "logic": 1,
    "knowledgeentity": 2,
    "knowledge_entity": 2,
    "entity": 2,
}
_MEMBER_NODE_KIND = {
    "claim": "claim",
    "logicstep": "logic",
    "logic_step": "logic",
    "logic": "logic",
    "knowledgeentity": "entity",
    "knowledge_entity": "entity",
    "entity": "entity",
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_kind(value: Any) -> str:
    return _clean_text(value).replace(" ", "").replace("-", "_").lower()


def _normalize_keywords(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values if isinstance(values, list) else []:
        keyword = _clean_text(raw)
        if not keyword:
            continue
        lowered = keyword.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(keyword)
    return out


def _community_sort_key(row: dict[str, Any]) -> tuple[int, int, str, str]:
    member_count = int(row.get("member_count") or 0)
    keywords = _normalize_keywords(row.get("keywords"))
    title = _clean_text(row.get("title"))
    community_id = _clean_text(row.get("community_id"))
    return (-member_count, -len(keywords), title.lower(), community_id.lower())


def _member_priority(row: dict[str, Any]) -> tuple[int, int, int, str, str]:
    normalized_kind = _normalize_kind(row.get("member_kind"))
    kind_rank = _MEMBER_KIND_PRIORITY.get(normalized_kind, 9)
    has_source = 0 if (_clean_text(row.get("paper_source")) or _clean_text(row.get("paper_id"))) else 1
    text = _clean_text(row.get("text"))
    return (
        kind_rank,
        has_source,
        -len(text),
        _clean_text(row.get("member_id")).lower(),
        text.lower(),
    )


def _tokenize_text(value: Any) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(_clean_text(value)) if len(token) >= 3}


def _member_node_id(row: dict[str, Any]) -> str:
    member_id = _clean_text(row.get("member_id"))
    kind = _MEMBER_NODE_KIND.get(_normalize_kind(row.get("member_kind")), "node")
    return f"{kind}:{member_id}" if member_id else f"{kind}:unknown"


def _member_label(row: dict[str, Any]) -> str:
    text = _clean_text(row.get("text"))
    if not text:
        return _clean_text(row.get("member_id")) or "Member"
    compact = " ".join(text.split())
    if len(compact) <= 72:
        return compact
    return f"{compact[:69].rstrip()}..."


def _member_description(row: dict[str, Any]) -> str | None:
    parts = []
    paper_source = _clean_text(row.get("paper_source"))
    paper_id = _clean_text(row.get("paper_id"))
    paper_title = _clean_text(row.get("paper_title"))
    step_type = _clean_text(row.get("step_type"))
    source_chapter_id = _clean_text(row.get("source_chapter_id"))
    text = _clean_text(row.get("text"))
    if paper_source:
        parts.append(paper_source)
    elif paper_id:
        parts.append(paper_id)
    if paper_title:
        parts.append(paper_title)
    if step_type:
        parts.append(step_type)
    if source_chapter_id:
        parts.append(source_chapter_id)
    if text:
        parts.append(text)
    description = " | ".join(parts)
    return description or None


def _pick_members(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not rows:
        return []

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(rows, key=_member_priority):
        buckets[_normalize_kind(row.get("member_kind"))].append(row)

    ordered_bucket_keys = sorted(
        buckets.keys(),
        key=lambda key: (_MEMBER_KIND_PRIORITY.get(key, 9), key),
    )

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    while len(selected) < limit:
        progressed = False
        for key in ordered_bucket_keys:
            bucket = buckets.get(key) or []
            while bucket:
                candidate = bucket.pop(0)
                member_id = _clean_text(candidate.get("member_id"))
                if not member_id or member_id in selected_ids:
                    continue
                selected.append(candidate)
                selected_ids.add(member_id)
                progressed = True
                break
            if len(selected) >= limit:
                break
        if not progressed:
            break

    if len(selected) < limit:
        for row in sorted(rows, key=_member_priority):
            member_id = _clean_text(row.get("member_id"))
            if not member_id or member_id in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(member_id)
            if len(selected) >= limit:
                break

    return selected


def build_overview_community_graph(
    community_rows: list[dict[str, Any]],
    members_by_community: dict[str, list[dict[str, Any]]],
    *,
    community_limit: int = 18,
    member_limit_per_community: int = 6,
    max_nodes: int = 160,
    max_edges: int = 240,
    max_community_links: int = 36,
) -> dict[str, Any]:
    safe_community_limit = max(1, min(80, int(community_limit or 1)))
    safe_member_limit = max(1, min(24, int(member_limit_per_community or 1)))
    safe_max_nodes = max(8, min(800, int(max_nodes or 8)))
    safe_max_edges = max(8, min(1600, int(max_edges or 8)))
    safe_max_community_links = max(0, min(200, int(max_community_links or 0)))

    ordered_communities = [
        dict(row)
        for row in sorted(
            [row for row in community_rows if _clean_text(row.get("community_id"))],
            key=_community_sort_key,
        )
    ]
    selected_communities = ordered_communities[: min(safe_community_limit, safe_max_nodes)]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    selected_members_by_community: dict[str, list[dict[str, Any]]] = {}

    total_member_count = 0
    visible_member_count = 0
    remaining_member_slots = max(0, safe_max_nodes - len(selected_communities))

    for index, community in enumerate(selected_communities):
        community_id = _clean_text(community.get("community_id"))
        community_node_id = f"community:{community_id}"
        keywords = _normalize_keywords(community.get("keywords"))
        total_members = members_by_community.get(community_id, [])
        total_member_count += len(total_members)

        communities_left = len(selected_communities) - index
        fair_share = math.ceil(remaining_member_slots / max(communities_left, 1)) if remaining_member_slots > 0 else 0
        member_budget = min(safe_member_limit, fair_share)
        visible_members = _pick_members(total_members, member_budget)
        selected_members_by_community[community_id] = visible_members
        visible_member_count += len(visible_members)
        remaining_member_slots = max(0, remaining_member_slots - len(visible_members))

        hidden_member_count = max(0, len(total_members) - len(visible_members))
        summary = _clean_text(community.get("summary"))
        keyword_label = ", ".join(keywords[:4])
        description_parts = []
        if summary:
            description_parts.append(summary)
        if keyword_label:
            description_parts.append(f"Keywords: {keyword_label}")
        description_parts.append(f"Visible members: {len(visible_members)}/{max(len(total_members), int(community.get('member_count') or 0))}")
        if hidden_member_count > 0:
            description_parts.append(f"Hidden members: {hidden_member_count}")

        nodes.append(
            {
                "id": community_node_id,
                "label": _clean_text(community.get("title")) or keyword_label or community_id,
                "kind": "community",
                "description": " | ".join(part for part in description_parts if part) or None,
                "cluster_key": community_node_id,
                "community_id": community_id,
                "keywords": keywords,
            }
        )

        for member in visible_members:
            normalized_kind = _normalize_kind(member.get("member_kind"))
            node_kind = _MEMBER_NODE_KIND.get(normalized_kind, "entity")
            member_node_id = _member_node_id(member)
            nodes.append(
                {
                    "id": member_node_id,
                    "label": _member_label(member),
                    "kind": node_kind,
                "description": _member_description(member),
                "cluster_key": community_node_id,
                "community_id": community_id,
                "paper_id": _clean_text(member.get("paper_id")) or None,
                "paper_source": _clean_text(member.get("paper_source")) or None,
                "paper_title": _clean_text(member.get("paper_title")) or None,
                "step_type": _clean_text(member.get("step_type")) or None,
                "chapter_id": _clean_text(member.get("source_chapter_id")) or None,
            }
        )
            edges.append(
                {
                    "id": f"contains:{community_node_id}->{member_node_id}",
                    "source": community_node_id,
                    "target": member_node_id,
                    "kind": "contains",
                    "weight": 0.92,
                }
            )

    community_link_candidates: list[tuple[float, str, str, list[str]]] = []
    for index, left in enumerate(selected_communities):
        left_id = _clean_text(left.get("community_id"))
        left_keywords = {item.lower() for item in _normalize_keywords(left.get("keywords"))}
        left_tokens = _tokenize_text(left.get("title")) | _tokenize_text(left.get("summary"))
        left_papers = {
            _clean_text(row.get("paper_id")) or _clean_text(row.get("paper_source"))
            for row in selected_members_by_community.get(left_id, [])
            if _clean_text(row.get("paper_id")) or _clean_text(row.get("paper_source"))
        }
        for right in selected_communities[index + 1 :]:
            right_id = _clean_text(right.get("community_id"))
            right_keywords = {item.lower() for item in _normalize_keywords(right.get("keywords"))}
            right_tokens = _tokenize_text(right.get("title")) | _tokenize_text(right.get("summary"))
            right_papers = {
                _clean_text(row.get("paper_id")) or _clean_text(row.get("paper_source"))
                for row in selected_members_by_community.get(right_id, [])
                if _clean_text(row.get("paper_id")) or _clean_text(row.get("paper_source"))
            }

            shared_keywords = sorted(left_keywords & right_keywords)
            shared_tokens = sorted((left_tokens & right_tokens) - set(shared_keywords))
            shared_papers = sorted(left_papers & right_papers)
            score = len(shared_keywords) * 1.0 + len(shared_tokens) * 0.12 + len(shared_papers) * 0.35
            if score <= 0:
                continue
            community_link_candidates.append((score, left_id, right_id, shared_keywords))

    community_link_candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    for score, left_id, right_id, shared_keywords in community_link_candidates[:safe_max_community_links]:
        if len(edges) >= safe_max_edges:
            break
        source = f"community:{left_id}"
        target = f"community:{right_id}"
        edges.append(
            {
                "id": f"similar:{source}->{target}",
                "source": source,
                "target": target,
                "kind": "similar",
                "weight": min(0.96, 0.34 + score * 0.16),
                "shared_keywords": shared_keywords,
            }
        )

    edges = edges[:safe_max_edges]

    hidden_communities = max(0, len(ordered_communities) - len(selected_communities))
    hidden_members = max(
        0,
        sum(len(members_by_community.get(_clean_text(row.get("community_id")), [])) for row in ordered_communities) - visible_member_count,
    )

    return {
        "nodes": nodes[:safe_max_nodes],
        "edges": edges,
        "stats": {
            "community_total": len(ordered_communities),
            "visible_communities": len(selected_communities),
            "visible_members": visible_member_count,
            "hidden_communities": hidden_communities,
            "hidden_members": hidden_members,
            "truncated": bool(hidden_communities or hidden_members or len(edges) >= safe_max_edges),
        },
    }
