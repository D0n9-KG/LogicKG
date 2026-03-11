from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from app.fusion.community import detect_fusion_communities
from app.fusion.keywords import extract_fusion_keywords

try:
    from networkx import MultiDiGraph as _NetworkXMultiDiGraph
except ModuleNotFoundError:
    _NetworkXMultiDiGraph = None


class _NodeView(dict[str, dict[str, Any]]):
    def __call__(self, data: bool = False):
        if data:
            return list(self.items())
        return list(self.keys())


class MultiDiGraph:
    def __init__(self) -> None:
        self.nodes = _NodeView()
        self._edges: list[tuple[str, str, dict[str, Any]]] = []

    def add_node(self, node_for_adding: Any, **attr: Any) -> None:
        self.nodes[str(node_for_adding)] = dict(attr)

    def add_edge(self, u_for_edge: Any, v_for_edge: Any, **attr: Any) -> None:
        self._edges.append((str(u_for_edge), str(v_for_edge), dict(attr)))

    def edges(self, data: bool = False):
        if data:
            return list(self._edges)
        return [(source, target) for source, target, _ in self._edges]

    def number_of_nodes(self) -> int:
        return len(self.nodes)

    def number_of_edges(self) -> int:
        return len(self._edges)


if _NetworkXMultiDiGraph is not None:
    MultiDiGraph = _NetworkXMultiDiGraph


def _graph_nodes(graph: Any) -> list[tuple[str, dict[str, Any]]]:
    nodes_attr = getattr(graph, "nodes", None)
    if callable(nodes_attr):
        return [(str(node_id), dict(data or {})) for node_id, data in nodes_attr(data=True)]
    if hasattr(nodes_attr, "__call__"):
        return [(str(node_id), dict(data or {})) for node_id, data in nodes_attr(data=True)]
    if isinstance(nodes_attr, dict):
        return [(str(node_id), dict(data or {})) for node_id, data in nodes_attr.items()]
    return []


def _graph_edges(graph: Any) -> list[tuple[str, str, dict[str, Any]]]:
    edges_attr = getattr(graph, "edges", None)
    if callable(edges_attr):
        return [(str(source), str(target), dict(data or {})) for source, target, data in edges_attr(data=True)]
    return []


def _community_id(member_ids: list[str]) -> str:
    seed = "|".join(sorted(member_ids))
    return "gc:" + hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _keyword_id(community_id: str, keyword: str) -> str:
    seed = f"{community_id}\0{keyword}"
    return "gk:" + hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _member_text(data: dict[str, Any]) -> str:
    properties = data.get("properties") if isinstance(data.get("properties"), dict) else {}
    for key in ("name", "summary", "text", "title"):
        text = str(properties.get(key) or data.get(key) or "").strip()
        if text:
            return text
    return ""


def run_tree_comm(
    graph: Any,
    *,
    top_keywords: int = 5,
    version: str = "v1",
) -> dict[str, list[dict[str, Any]]]:
    node_rows: list[dict[str, Any]] = []
    for node_id, data in _graph_nodes(graph):
        text = _member_text(data)
        if not text:
            continue
        node_rows.append(
            {
                "id": node_id,
                "text": text,
                "evidence_quote": text[:220],
            }
        )

    edge_rows: list[dict[str, Any]] = []
    for source, target, data in _graph_edges(graph):
        relation = str(data.get("relation") or data.get("type") or "").strip()
        if not relation:
            continue
        edge_rows.append(
            {
                "source": source,
                "target": target,
                "type": relation,
                "weight": float(data.get("weight") or data.get("score") or 1.0),
            }
        )

    detected = detect_fusion_communities(node_rows, edge_rows)
    built_at = datetime.now(tz=timezone.utc).isoformat()

    communities: list[dict[str, Any]] = []
    for row in detected:
        member_ids = [str(item).strip() for item in (row.get("member_ids") or []) if str(item).strip()]
        if not member_ids:
            continue
        communities.append(
            {
                "community_id": _community_id(member_ids),
                "title": str(row.get("title") or "").strip() or _community_id(member_ids),
                "summary": str(row.get("representative_evidence") or row.get("title") or "").strip(),
                "confidence": float(row.get("confidence") or row.get("weight") or 0.0),
                "member_count": len(member_ids),
                "member_ids": member_ids,
                "version": str(version or "v1").strip() or "v1",
                "built_at": built_at,
            }
        )

    keyword_seed_rows = extract_fusion_keywords(communities, node_rows, top_k=max(1, int(top_keywords)))
    keywords: list[dict[str, Any]] = []
    for row in keyword_seed_rows:
        community_id = str(row.get("community_id") or "").strip()
        keyword = str(row.get("keyword") or "").strip()
        if not community_id or not keyword:
            continue
        keywords.append(
            {
                "community_id": community_id,
                "keyword_id": _keyword_id(community_id, keyword),
                "keyword": keyword,
                "rank": int(row.get("rank") or 0),
                "weight": float(row.get("weight") or 0.0),
            }
        )

    communities.sort(key=lambda item: str(item.get("community_id") or ""))
    keywords.sort(key=lambda item: (str(item.get("community_id") or ""), int(item.get("rank") or 0), str(item.get("keyword") or "")))
    return {
        "communities": communities,
        "keywords": keywords,
    }
