from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.fusion.builder import build_fusion_projection
from app.fusion.community import detect_fusion_communities
from app.fusion.keywords import extract_fusion_keywords
from app.graph.neo4j_client import Neo4jClient
from app.rag.fusion_retrieval import rank_fusion_basics
from app.settings import settings


ProgressFn = Callable[[str, float, str | None], None]
LogFn = Callable[[str], None]


def _noop_progress(stage: str, p: float, msg: str | None = None) -> None:
    pass


def _noop_log(line: str) -> None:
    pass


def _snapshot_dir() -> Path:
    p = Path(__file__).resolve().parents[2] / settings.storage_dir / "fusion"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _snapshot_file() -> Path:
    return _snapshot_dir() / "latest_graph.json"


def _normalize_explains_links(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize EXPLAINS edges into Neo4j writer payload keys."""
    rows: list[dict[str, Any]] = []
    for edge in edges:
        sid = str(edge.get("logic_step_id") or edge.get("source") or "").strip()
        eid = str(edge.get("entity_id") or edge.get("target") or "").strip()
        if not sid or not eid:
            continue
        row = dict(edge)
        row["logic_step_id"] = sid
        row["entity_id"] = eid
        if row.get("score") is None and row.get("weight") is not None:
            row["score"] = row.get("weight")
        rows.append(row)
    return rows


def _sanitize_graph_payload(
    nodes_raw: list[dict[str, Any]] | None,
    edges_raw: list[dict[str, Any]] | None,
    *,
    limit_nodes: int,
    limit_edges: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    node_limit = max(1, int(limit_nodes))
    edge_limit = max(1, int(limit_edges))

    all_nodes: list[dict[str, Any]] = []
    node_map: dict[str, dict[str, Any]] = {}
    node_order: list[str] = []
    for raw in list(nodes_raw or []):
        node = dict(raw or {})
        node_id = str(node.get("id") or "").strip()
        if not node_id or node_id in node_map:
            continue
        node["id"] = node_id
        all_nodes.append(node)
        node_map[node_id] = node
        node_order.append(node_id)

    all_edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    degree: dict[str, int] = {}
    for raw in list(edges_raw or []):
        edge = dict(raw or {})
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            continue
        if source not in node_map or target not in node_map:
            continue
        edge_type = str(edge.get("type") or "").strip()
        edge_key = (source, target, edge_type)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        edge["source"] = source
        edge["target"] = target
        all_edges.append(edge)
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1

    if len(node_map) <= node_limit and len(all_edges) <= edge_limit:
        return all_nodes, all_edges

    def edge_score(edge: dict[str, Any]) -> tuple[float, int]:
        edge_type = str(edge.get("type") or "").strip()
        type_bonus = {
            "EXPLAINS": 5,
            "RELATES_TO": 4,
            "HAS_CLAIM": 3,
            "IN_COMMUNITY": 2,
            "HAS_KEYWORD": 1,
        }.get(edge_type, 0)
        weight = float(edge.get("weight") or 0.0)
        return (type_bonus + weight, max(degree.get(str(edge.get("source") or ""), 0), degree.get(str(edge.get("target") or ""), 0)))

    ranked_edges = sorted(all_edges, key=edge_score, reverse=True)
    selected_node_ids: set[str] = set()
    selected_edges: list[dict[str, Any]] = []

    for edge in ranked_edges:
        if len(selected_edges) >= edge_limit:
            break
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        extra_nodes = int(source not in selected_node_ids) + int(target not in selected_node_ids)
        if len(selected_node_ids) + extra_nodes > node_limit:
            continue
        selected_edges.append(edge)
        selected_node_ids.add(source)
        selected_node_ids.add(target)

    if not selected_node_ids:
        ranked_node_ids = sorted(
            node_order,
            key=lambda node_id: (degree.get(node_id, 0), -node_order.index(node_id)),
            reverse=True,
        )
        selected_node_ids.update(ranked_node_ids[:node_limit])
    elif len(selected_node_ids) < node_limit:
        for node_id in node_order:
            if node_id in selected_node_ids:
                continue
            selected_node_ids.add(node_id)
            if len(selected_node_ids) >= node_limit:
                break

    nodes = [node_map[node_id] for node_id in node_order if node_id in selected_node_ids][:node_limit]
    selected_lookup = {node["id"] for node in nodes}
    edges = [
        edge
        for edge in ranked_edges
        if str(edge.get("source") or "") in selected_lookup and str(edge.get("target") or "") in selected_lookup
    ][:edge_limit]

    return nodes, edges


def rebuild_fusion_graph(
    *,
    paper_id: str | None = None,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    progress = progress or _noop_progress
    log = log or _noop_log

    progress("fusion:init", 0.02, "Loading paper and textbook graph inputs")
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        client.ensure_schema()
        logic_steps = client.list_logic_steps_for_fusion(paper_id=paper_id, limit=50000)
        claims = client.list_claims_for_fusion(paper_id=paper_id, limit=50000)
        entities = client.list_textbook_entities_for_fusion(limit=50000)
        relations = client.list_textbook_relations_for_fusion(limit=100000)

        progress("fusion:linking", 0.35, "Building cross-source EXPLAINS links")
        projection = build_fusion_projection(
            logic_steps=logic_steps,
            claims=claims,
            entities=entities,
            textbook_relations=relations,
            min_link_score=0.45,
            top_k_per_step=3,
        )
        explains_edges = [e for e in projection["edges"] if str(e.get("type")) == "EXPLAINS"]
        explains_links = _normalize_explains_links(explains_edges)
        explains_written = client.create_fusion_explains_edges(explains_links)
        log(f"fusion explains written: {explains_written}")

        progress("fusion:community", 0.62, "Detecting fusion communities")
        community_nodes = []
        for node in projection["nodes"]:
            text = str(node.get("summary") or node.get("text") or node.get("name") or "").strip()
            community_nodes.append(
                {
                    "id": str(node.get("id") or ""),
                    "text": text,
                    "evidence_quote": text[:220],
                }
            )
        community_edges = []
        for edge in projection["edges"]:
            edge_type = str(edge.get("type") or "")
            if edge_type not in {"EXPLAINS", "RELATES_TO", "HAS_CLAIM"}:
                continue
            community_edges.append(
                {
                    "source": str(edge.get("source") or ""),
                    "target": str(edge.get("target") or ""),
                    "type": edge_type,
                    "weight": float(edge.get("score") or edge.get("weight") or 0.8),
                }
            )
        communities = detect_fusion_communities(community_nodes, community_edges)
        communities_written = client.upsert_fusion_communities(communities)

        keywords = extract_fusion_keywords(communities, community_nodes, top_k=5)
        keywords_written = client.upsert_fusion_keywords(keywords)
        log(f"fusion communities/keywords written: {communities_written}/{keywords_written}")

    progress("fusion:snapshot", 0.84, "Writing fusion snapshot")
    snapshot = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "paper_id_scope": str(paper_id or ""),
        "nodes": projection["nodes"],
        "edges": projection["edges"],
        "communities": communities,
        "keywords": keywords,
    }
    _snapshot_file().write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    progress("fusion:done", 1.0, "Fusion rebuild completed")
    return {
        "ok": True,
        "paper_id_scope": str(paper_id or ""),
        "logic_steps": len(logic_steps),
        "claims": len(claims),
        "entities": len(entities),
        "relations": len(relations),
        "explains_written": int(explains_written),
        "communities": len(communities),
        "keywords": len(keywords),
        "snapshot_file": str(_snapshot_file()),
    }


def get_fusion_graph(*, limit_nodes: int = 1000, limit_edges: int = 3000) -> dict[str, Any]:
    path = _snapshot_file()
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        nodes, edges = _sanitize_graph_payload(
            data.get("nodes") or [],
            data.get("edges") or [],
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
        return {
            "nodes": nodes,
            "edges": edges,
            "source": "snapshot",
            "generated_at": data.get("generated_at"),
        }

    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        graph = client.list_fusion_graph(limit_nodes=limit_nodes, limit_edges=limit_edges)
    nodes, edges = _sanitize_graph_payload(
        graph.get("nodes") or [],
        graph.get("edges") or [],
        limit_nodes=limit_nodes,
        limit_edges=limit_edges,
    )
    return {
        "nodes": nodes,
        "edges": edges,
        "source": "neo4j",
        "generated_at": None,
    }


def list_fusion_sections_for_paper(paper_id: str) -> dict[str, Any]:
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        sections = client.list_fusion_sections_for_paper(paper_id)
    return {"paper_id": paper_id, "sections": sections}


def list_fusion_basics_for_section(paper_id: str, step_type: str, limit: int = 50) -> dict[str, Any]:
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        basics = client.list_fusion_basics_for_section(paper_id, step_type, limit=limit)
    return {"paper_id": paper_id, "step_type": step_type, "basics": basics}


def retrieve_fusion_basics(
    *,
    question: str,
    paper_id: str,
    step_type: str | None = None,
    k: int = 8,
) -> dict[str, Any]:
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        if step_type:
            rows = client.list_fusion_basics_for_section(paper_id, step_type, limit=max(30, k * 5))
        else:
            rows = []
            sections = client.list_fusion_sections_for_paper(paper_id)
            for sec in sections[:10]:
                st = str(sec.get("step_type") or "").strip()
                if not st:
                    continue
                rows.extend(client.list_fusion_basics_for_section(paper_id, st, limit=20))

    ranked = rank_fusion_basics(question, rows, k=k)
    return {
        "paper_id": paper_id,
        "step_type": step_type,
        "items": ranked,
    }
