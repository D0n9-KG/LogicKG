from __future__ import annotations

from typing import Any

from app.fusion.linking import generate_explains_links


def build_fusion_projection(
    logic_steps: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    textbook_relations: list[dict[str, Any]],
    *,
    min_link_score: float = 0.45,
    top_k_per_step: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    links = generate_explains_links(
        logic_steps,
        entities,
        min_score=min_link_score,
        top_k_per_step=top_k_per_step,
    )

    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for step in logic_steps:
        sid = str(step.get("logic_step_id") or "").strip()
        if not sid:
            continue
        nodes_by_id[sid] = {
            "id": sid,
            "label": "LogicStep",
            "step_type": step.get("step_type"),
            "summary": step.get("summary"),
        }

    for claim in claims:
        cid = str(claim.get("claim_id") or "").strip()
        if not cid:
            continue
        nodes_by_id[cid] = {
            "id": cid,
            "label": "Claim",
            "text": claim.get("text"),
            "step_type": claim.get("step_type"),
        }
        c_step_type = str(claim.get("step_type") or "")
        for step in logic_steps:
            if str(step.get("step_type") or "") != c_step_type:
                continue
            sid = str(step.get("logic_step_id") or "").strip()
            if not sid:
                continue
            edges.append({"type": "HAS_CLAIM", "source": sid, "target": cid})
            break

    for ent in entities:
        eid = str(ent.get("entity_id") or "").strip()
        if not eid:
            continue
        nodes_by_id[eid] = {
            "id": eid,
            "label": "KnowledgeEntity",
            "name": ent.get("name"),
            "entity_type": ent.get("entity_type"),
        }

    for rel in textbook_relations:
        s = str(rel.get("start_id") or "").strip()
        t = str(rel.get("end_id") or "").strip()
        if not s or not t:
            continue
        edges.append(
            {
                "type": "RELATES_TO",
                "source": s,
                "target": t,
                "rel_type": rel.get("rel_type"),
            }
        )

    for link in links:
        edges.append(
            {
                "type": "EXPLAINS",
                "source": link["logic_step_id"],
                "target": link["entity_id"],
                "score": link.get("score"),
                "reasons": link.get("reasons"),
                "evidence_chunk_ids": link.get("evidence_chunk_ids"),
            }
        )

    return {
        "nodes": list(nodes_by_id.values()),
        "edges": edges,
    }
