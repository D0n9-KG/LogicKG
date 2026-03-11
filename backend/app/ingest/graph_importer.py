"""Youtu graph.json → LogicKG Neo4j importer.

Reads the graph JSON produced by Youtu-GraphRAG and writes
KnowledgeEntity nodes + RELATES_TO edges into the LogicKG Neo4j
database, linked to the appropriate TextbookChapter.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from app.community.remote_graph_normalizer import normalize_remote_graph_payload
from app.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


def _entity_id(textbook_id: str, chapter_id: str, source_node_id: str, entity_type: str) -> str:
    """Deterministic entity ID: avoids cross-textbook collisions."""
    seed = f"ke:v1\0{textbook_id}\0{chapter_id}\0{source_node_id}\0{entity_type}"
    return hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _merge_attributes(node: dict) -> str:
    """Extract extra attributes from a Youtu node as a JSON string."""
    props = dict(node.get("properties", {}) or {})
    # Remove fields already stored as first-class properties
    for key in ("name", "description", "id", "community_id"):
        props.pop(key, None)
    return json.dumps(props, ensure_ascii=False) if props else "{}"


def _node_source_id(node: dict) -> str:
    """Stable source id for Youtu nodes.

    Supports both explicit ``id`` and id-less triple list payloads where a
    node is represented only by ``label`` + ``properties``.
    """
    if not isinstance(node, dict):
        return ""
    props = node.get("properties") or {}
    explicit = str(node.get("id") or props.get("id") or "").strip()
    if explicit:
        return explicit
    seed_obj = {
        "label": str(node.get("label") or "").strip().lower(),
        "name": str(props.get("name") or "").strip(),
        "chunk_id": str(props.get("chunk id") or props.get("chunk_id") or "").strip(),
        "schema_type": str(props.get("schema_type") or "").strip().lower(),
    }
    seed = json.dumps(seed_obj, ensure_ascii=False, sort_keys=True)
    return "anon:" + hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _normalize_youtu_payload(data: Any) -> tuple[list[dict], list[dict], list[dict]]:
    """Normalize Youtu payloads to ``(nodes, edges, communities)``.

    Supported formats:
    - Dict payload: ``{nodes, edges, communities}``
    - List payload: ``[{start_node, relation, end_node}, ...]``
    """
    if isinstance(data, dict):
        nodes = data.get("nodes") or []
        edges = data.get("edges") or []
        communities = data.get("communities") or []
        return list(nodes), list(edges), list(communities)

    if isinstance(data, list):
        node_map: dict[str, dict] = {}
        edges: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            start_node = dict(item.get("start_node") or {})
            end_node = dict(item.get("end_node") or {})
            start_id = _node_source_id(start_node)
            end_id = _node_source_id(end_node)
            if not start_id or not end_id:
                continue
            if start_id not in node_map:
                start_node["id"] = start_id
                node_map[start_id] = start_node
            if end_id not in node_map:
                end_node["id"] = end_id
                node_map[end_id] = end_node
            edges.append({
                "start_id": start_id,
                "end_id": end_id,
                "relation": str(item.get("relation") or item.get("type") or "related_to"),
            })
        return list(node_map.values()), edges, []

    raise ValueError(f"Unsupported Youtu graph payload type: {type(data).__name__}")


def import_youtu_graph(
    graph_json_path: str,
    textbook_id: str,
    chapter_id: str,
    neo4j_client: Neo4jClient,
) -> dict[str, Any]:
    """Import a Youtu graph.json into LogicKG Neo4j.

    Mapping:
    - Youtu ``nodes`` → :class:`KnowledgeEntity` nodes
    - Youtu ``edges`` → ``RELATES_TO`` relationships
    - remote chapter-local ``community`` / ``keyword`` / ``super-node`` artifacts are discarded
    - ``TextbookChapter -[:HAS_ENTITY]-> KnowledgeEntity`` links created

    Returns:
        ``{entity_count, relation_count, community_count}``
    """
    raw = Path(graph_json_path).read_text(encoding="utf-8", errors="replace")
    data = normalize_remote_graph_payload(json.loads(raw))
    nodes, edges, communities = _normalize_youtu_payload(data)

    # Build Youtu-ID → LogicKG entity_id mapping
    id_map: dict[str, str] = {}

    # --- Entities ---
    entities: list[dict] = []
    for node in nodes:
        source_id = str(node.get("id") or "").strip()
        if not source_id:
            continue
        etype = str(node.get("label") or "unknown").strip().lower()
        eid = _entity_id(textbook_id, chapter_id, source_id, etype)
        id_map[source_id] = eid

        props = node.get("properties") or {}
        attrs = _merge_attributes(node)

        entities.append({
            "entity_id": eid,
            "name": str(props.get("name") or source_id),
            "entity_type": etype,
            "description": str(props.get("description") or ""),
            "attributes": attrs,
            "source_chapter_id": chapter_id,
        })

    # --- Relations ---
    relations: list[dict] = []
    for edge in edges:
        src = str(edge.get("start_id") or edge.get("source") or "").strip()
        tgt = str(edge.get("end_id") or edge.get("target") or "").strip()
        if not src or not tgt:
            continue
        mapped_src = id_map.get(src)
        mapped_tgt = id_map.get(tgt)
        if not mapped_src or not mapped_tgt:
            logger.warning("Skipping edge with unmapped node: %s -> %s", src, tgt)
            continue
        relations.append({
            "start_id": mapped_src,
            "end_id": mapped_tgt,
            "rel_type": str(edge.get("relation") or edge.get("type") or "related_to"),
        })

    # --- Write to Neo4j ---
    entity_count = neo4j_client.create_knowledge_entities(entities)
    relation_count = neo4j_client.create_entity_relations(relations)
    neo4j_client.link_chapter_entities(chapter_id, [e["entity_id"] for e in entities])

    logger.info(
        "Imported graph for chapter %s: %d entities, %d relations, %d communities",
        chapter_id, entity_count, relation_count, len(communities),
    )
    return {
        "entity_count": entity_count,
        "relation_count": relation_count,
        "community_count": len(communities),
    }
