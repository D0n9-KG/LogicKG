from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.settings import settings

try:
    from networkx import MultiDiGraph as _NetworkXMultiDiGraph
except ModuleNotFoundError:
    _NetworkXMultiDiGraph = None


class _NodeView(dict[str, dict[str, Any]]):
    def __call__(self, data: bool = False):
        if data:
            return list(self.items())
        return list(self.keys())


class _EdgeView:
    def __init__(self, graph: "MultiDiGraph") -> None:
        self._graph = graph

    def __call__(self, data: bool = False):
        if data:
            return list(self._graph._edges)
        return [(source, target) for source, target, _ in self._graph._edges]

    def __getitem__(self, key: tuple[Any, Any, int]):
        source, target, edge_key = key
        return self._graph._adj[str(source)][str(target)][int(edge_key)]


class MultiDiGraph:
    def __init__(self) -> None:
        self.nodes = _NodeView()
        self._edges: list[tuple[str, str, dict[str, Any]]] = []
        self._adj: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
        self.edges = _EdgeView(self)

    def add_node(self, node_for_adding: Any, **attr: Any) -> None:
        node_id = str(node_for_adding)
        self.nodes[node_id] = dict(attr)
        self._adj.setdefault(node_id, {})

    def add_edge(self, u_for_edge: Any, v_for_edge: Any, **attr: Any) -> None:
        source = str(u_for_edge)
        target = str(v_for_edge)
        self._adj.setdefault(source, {})
        self._adj.setdefault(target, {})
        keyed_edges = self._adj[source].setdefault(target, {})
        edge_key = len(keyed_edges)
        edge_data = dict(attr)
        keyed_edges[edge_key] = edge_data
        self._edges.append((source, target, edge_data))

    def neighbors(self, node: Any):
        return list(self._adj.get(str(node), {}).keys())

    def degree(self, node: Any | None = None) -> int | dict[str, int]:
        if node is None:
            return {node_id: self.degree(node_id) for node_id in self.nodes.keys()}
        node_id = str(node)
        out_degree = sum(len(edges) for edges in self._adj.get(node_id, {}).values())
        in_degree = 0
        for source, targets in self._adj.items():
            if source == node_id:
                continue
            in_degree += len(targets.get(node_id, {}))
        return out_degree + in_degree

    def number_of_nodes(self) -> int:
        return len(self.nodes)

    def number_of_edges(self) -> int:
        return len(self._edges)

if _NetworkXMultiDiGraph is not None:
    MultiDiGraph = _NetworkXMultiDiGraph


FastTreeComm = None


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


def _resolve_fast_tree_comm():
    if FastTreeComm is not None:
        return FastTreeComm
    try:
        from vendor.youtu_graphrag.utils.tree_comm import FastTreeComm as vendored_fast_tree_comm
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Vendored Youtu TreeComm dependencies are unavailable. "
            "Install backend requirements to enable global community clustering."
        ) from exc
    return vendored_fast_tree_comm


def _keyword_text(graph: Any, node_id: str) -> str:
    nodes_attr = getattr(graph, "nodes", None)
    if nodes_attr is None:
        return ""
    try:
        data = dict(nodes_attr[node_id] or {})
    except Exception:
        return ""
    return _member_text(data)


def _community_title(keyword_texts: list[str], member_ids: list[str], graph: Any) -> str:
    if keyword_texts:
        return " / ".join(keyword_texts[:3])
    fallback = [_keyword_text(graph, node_id) for node_id in member_ids[:3]]
    fallback = [text for text in fallback if text]
    if fallback:
        return " / ".join(fallback)
    return _community_id(member_ids)


def _community_summary(keyword_texts: list[str], member_ids: list[str], graph: Any) -> str:
    preview = [_keyword_text(graph, node_id) for node_id in member_ids[:4]]
    preview = [text for text in preview if text]
    if keyword_texts and preview:
        return f"TreeComm keywords: {', '.join(keyword_texts[:5])}. Members: {', '.join(preview[:4])}."
    if preview:
        return "Members: " + ", ".join(preview[:4])
    if keyword_texts:
        return "TreeComm keywords: " + ", ".join(keyword_texts[:5])
    return ""


def run_tree_comm(
    graph: Any,
    *,
    top_keywords: int = 5,
    version: str = "v1",
    embedding_model: str | None = None,
    struct_weight: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    candidate_nodes = [node_id for node_id, data in _graph_nodes(graph) if _member_text(data)]
    built_at = datetime.now(tz=timezone.utc).isoformat()
    if not candidate_nodes:
        return {"communities": [], "keywords": []}

    fast_tree_comm_cls = _resolve_fast_tree_comm()
    tree_comm = fast_tree_comm_cls(
        graph,
        embedding_model=embedding_model or settings.global_community_tree_comm_embedding_model,
        struct_weight=float(
            settings.global_community_tree_comm_struct_weight if struct_weight is None else struct_weight
        ),
        config=None,
    )
    detected = tree_comm.detect_communities(candidate_nodes)

    communities: list[dict[str, Any]] = []
    keywords: list[dict[str, Any]] = []
    for _, members in sorted(detected.items(), key=lambda item: str(item[0])):
        member_ids = [str(item).strip() for item in members if str(item).strip()]
        if not member_ids:
            continue
        keyword_nodes = tree_comm.extract_keywords_from_community(member_ids, top_k=max(1, int(top_keywords)))
        keyword_texts = [_keyword_text(graph, str(node_id or "").strip()) for node_id in keyword_nodes]
        keyword_texts = [text for text in keyword_texts if text]
        community_id = _community_id(member_ids)
        communities.append(
            {
                "community_id": community_id,
                "title": _community_title(keyword_texts, member_ids, graph),
                "summary": _community_summary(keyword_texts, member_ids, graph),
                "confidence": 1.0,
                "member_count": len(member_ids),
                "member_ids": member_ids,
                "version": str(version or "v1").strip() or "v1",
                "built_at": built_at,
            }
        )
        for rank, keyword in enumerate(keyword_texts[: max(1, int(top_keywords))], start=1):
            keywords.append(
                {
                    "community_id": community_id,
                    "keyword_id": _keyword_id(community_id, keyword),
                    "keyword": keyword,
                    "rank": rank,
                    "weight": float(1.0 / rank),
                }
            )

    communities.sort(key=lambda item: str(item.get("community_id") or ""))
    keywords.sort(key=lambda item: (str(item.get("community_id") or ""), int(item.get("rank") or 0), str(item.get("keyword") or "")))
    return {
        "communities": communities,
        "keywords": keywords,
    }
