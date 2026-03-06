from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.graph.neo4j_client import Neo4jClient
from app.discovery.prompt_policy import feedback_label_reward, update_prompt_policy_reward
from app.settings import settings


_LOCAL_SCORES: dict[str, float] = {}
_DELTA_BY_LABEL = {
    "accepted": 0.2,
    "rejected": -0.2,
    "needs_revision": -0.05,
}
_WEIGHT_BY_LABEL = {
    "accepted": 1.0,
    "rejected": -1.0,
    "needs_revision": -0.25,
}


def _normalized_label(label: str) -> str:
    v = str(label or "").strip().lower()
    if v in {"accepted", "rejected", "needs_revision"}:
        return v
    return "needs_revision"


def apply_feedback(candidate_id: str, label: str, note: str | None = None) -> dict:
    cid = str(candidate_id or "").strip()
    if not cid:
        raise ValueError("candidate_id is required")

    normalized_label = _normalized_label(label)
    delta = float(_DELTA_BY_LABEL.get(normalized_label, -0.05))
    weight = float(_WEIGHT_BY_LABEL.get(normalized_label, -0.25))
    now = datetime.now(tz=timezone.utc).isoformat()
    feedback_id = f"fb:{uuid.uuid4().hex[:12]}"

    # Always keep local fallback score so feature works even when Neo4j is offline.
    local_prev = float(_LOCAL_SCORES.get(cid, 0.0))
    local_new = local_prev + delta
    _LOCAL_SCORES[cid] = local_new

    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            cypher = """
MERGE (rq:ResearchQuestionCandidate {candidate_id: $candidate_id})
ON CREATE SET rq.question = coalesce(rq.question, $default_question),
              rq.quality_score = coalesce(rq.quality_score, 0.0),
              rq.status = coalesce(rq.status, 'draft')
WITH rq
CREATE (fb:FeedbackRecord {
    feedback_id: $feedback_id,
    candidate_id: $candidate_id,
    label: $label,
    note: $note,
    weight: $weight,
    created_at: $created_at
})
MERGE (fb)-[:FEEDBACK_FOR]->(rq)
SET rq.quality_score = coalesce(rq.quality_score, 0.0) + $delta,
    rq.status = CASE
        WHEN $label = 'accepted' THEN 'accepted'
        WHEN $label = 'rejected' THEN 'rejected'
        ELSE coalesce(rq.status, 'ranked')
    END,
    rq.last_feedback_at = $created_at
RETURN rq.quality_score AS updated_score
"""
            with client._driver.session() as session:  # noqa: SLF001
                row = session.run(
                    cypher,
                    candidate_id=cid,
                    feedback_id=feedback_id,
                    label=normalized_label,
                    note=str(note) if note is not None else None,
                    weight=weight,
                    created_at=now,
                    delta=delta,
                    default_question="Candidate created from feedback bootstrap",
                ).single()
                meta = session.run(
                    """
MATCH (rq:ResearchQuestion {rq_id:$candidate_id})
RETURN rq.domain AS domain, rq.gap_type AS gap_type, rq.prompt_variant AS prompt_variant
LIMIT 1
""",
                    candidate_id=cid,
                ).single()
            updated_score = float(row["updated_score"]) if row and row.get("updated_score") is not None else local_new
            _LOCAL_SCORES[cid] = updated_score
            if meta:
                prompt_variant = str(meta.get("prompt_variant") or "").strip()
                if prompt_variant:
                    update_prompt_policy_reward(
                        domain=str(meta.get("domain") or "default"),
                        gap_type=str(meta.get("gap_type") or "seed"),
                        prompt_variant=prompt_variant,
                        reward=feedback_label_reward(normalized_label),
                        source="human_feedback",
                    )
            return {
                "candidate_id": cid,
                "feedback_id": feedback_id,
                "label": normalized_label,
                "updated_score": updated_score,
                "stored_in": "neo4j",
            }
    except Exception:
        return {
            "candidate_id": cid,
            "feedback_id": feedback_id,
            "label": normalized_label,
            "updated_score": local_new,
            "stored_in": "memory",
        }
