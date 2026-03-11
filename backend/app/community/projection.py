from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.community.tree_comm_adapter import MultiDiGraph


def _node_payload(label: str, text: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "label": label,
        "properties": {
            "name": str(text or "").strip(),
        },
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def build_global_projection(*, client: Any) -> MultiDiGraph:
    graph = MultiDiGraph()

    entity_ids: set[str] = set()
    for row in client.list_textbook_entities_for_fusion(limit=50000) or []:
        entity_id = str(row.get("entity_id") or "").strip()
        text = str(row.get("name") or row.get("description") or "").strip()
        if not entity_id or not text:
            continue
        entity_ids.add(entity_id)
        graph.add_node(
            entity_id,
            **_node_payload(
                "KnowledgeEntity",
                text,
                entity_type=str(row.get("entity_type") or "").strip() or None,
                source_chapter_id=str(row.get("source_chapter_id") or "").strip() or None,
            ),
        )

    for row in client.list_textbook_relations_for_fusion(limit=100000) or []:
        source_id = str(row.get("start_id") or "").strip()
        target_id = str(row.get("end_id") or "").strip()
        relation = str(row.get("rel_type") or "RELATES_TO").strip() or "RELATES_TO"
        if source_id not in entity_ids or target_id not in entity_ids:
            continue
        graph.add_edge(source_id, target_id, relation=relation)

    logic_by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in client.list_logic_steps_for_fusion(limit=50000) or []:
        logic_step_id = str(row.get("logic_step_id") or "").strip()
        text = str(row.get("summary") or "").strip()
        paper_id = str(row.get("paper_id") or "").strip()
        step_type = str(row.get("step_type") or "").strip()
        if not logic_step_id or not text:
            continue
        if paper_id and step_type:
            logic_by_key[(paper_id, step_type)].append(logic_step_id)
        graph.add_node(
            logic_step_id,
            **_node_payload(
                "LogicStep",
                text,
                paper_id=paper_id or None,
                paper_source=str(row.get("paper_source") or "").strip() or None,
                step_type=step_type or None,
            ),
        )

    for row in client.list_claims_for_fusion(limit=50000) or []:
        claim_id = str(row.get("claim_id") or "").strip()
        text = str(row.get("text") or "").strip()
        paper_id = str(row.get("paper_id") or "").strip()
        step_type = str(row.get("step_type") or "").strip()
        if not claim_id or not text:
            continue
        graph.add_node(
            claim_id,
            **_node_payload(
                "Claim",
                text,
                paper_id=paper_id or None,
                paper_source=str(row.get("paper_source") or "").strip() or None,
                step_type=step_type or None,
                confidence=row.get("confidence"),
            ),
        )
        for logic_step_id in logic_by_key.get((paper_id, step_type), []):
            graph.add_edge(logic_step_id, claim_id, relation="HAS_CLAIM")

    return graph
