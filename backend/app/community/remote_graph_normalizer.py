from __future__ import annotations

from typing import Any

_REMOTE_ONLY_LABELS = {
    "community",
    "keyword",
    "super-node",
    "super_node",
    "supernode",
}

_REMOTE_ONLY_RELATIONS = {
    "member_of",
    "keyword_of",
    "represented_by",
    "kw_filter_by",
    "belongs_to",
    "describes",
}


def _node_label(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("label") or "").strip().lower()


def _relation_name(edge: Any) -> str:
    if not isinstance(edge, dict):
        return ""
    return str(edge.get("relation") or edge.get("type") or "").strip().lower()


def normalize_remote_graph_payload(data: Any) -> Any:
    if isinstance(data, list):
        kept = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if _node_label(item.get("start_node")) in _REMOTE_ONLY_LABELS:
                continue
            if _node_label(item.get("end_node")) in _REMOTE_ONLY_LABELS:
                continue
            if _relation_name(item) in _REMOTE_ONLY_RELATIONS:
                continue
            kept.append(dict(item))
        return kept

    if not isinstance(data, dict):
        return data

    nodes = [dict(node) for node in (data.get("nodes") or []) if _node_label(node) not in _REMOTE_ONLY_LABELS]
    allowed_ids = {
        str(node.get("id") or node.get("properties", {}).get("id") or "").strip()
        for node in nodes
        if isinstance(node, dict)
    }
    allowed_ids.discard("")

    edges: list[dict] = []
    for raw_edge in data.get("edges") or []:
        if not isinstance(raw_edge, dict):
            continue
        relation = _relation_name(raw_edge)
        if relation in _REMOTE_ONLY_RELATIONS:
            continue
        source_id = str(raw_edge.get("start_id") or raw_edge.get("source") or "").strip()
        target_id = str(raw_edge.get("end_id") or raw_edge.get("target") or "").strip()
        if source_id not in allowed_ids or target_id not in allowed_ids:
            continue
        edges.append(dict(raw_edge))

    normalized = dict(data)
    normalized["nodes"] = nodes
    normalized["edges"] = edges
    normalized["communities"] = []
    return normalized
