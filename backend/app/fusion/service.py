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

    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for raw in list(nodes_raw or [])[:node_limit]:
        node = dict(raw or {})
        node_id = str(node.get("id") or "").strip()
        if not node_id or node_id in node_ids:
            continue
        node["id"] = node_id
        nodes.append(node)
        node_ids.add(node_id)

    edges: list[dict[str, Any]] = []
    for raw in list(edges_raw or [])[:edge_limit]:
        edge = dict(raw or {})
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            continue
        if source not in node_ids or target not in node_ids:
            continue
        edge["source"] = source
        edge["target"] = target
        edges.append(edge)

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
