from __future__ import annotations

from app.graph.neo4j_client import (
    normalize_proposition_text,
    proposition_id_for_key,
    proposition_key_for_claim,
)


ASSERTIVE_ENTITY_TYPES = {"theory", "equation", "method", "model", "condition"}


def _canonical_text(name: str, description: str) -> str:
    name_s = str(name or "").strip()
    desc_s = str(description or "").strip()
    if name_s and desc_s:
        base = f"{name_s}. {desc_s}"
    else:
        base = name_s or desc_s
    if not base:
        base = "unnamed proposition"
    return normalize_proposition_text(base)


def map_entities_to_propositions(items: list[dict]) -> list[dict]:
    """Map textbook KnowledgeEntity rows to Proposition upsert payload."""
    mapped: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for raw in items or []:
        entity_id = str(raw.get("entity_id") or "").strip()
        entity_type = str(raw.get("entity_type") or "").strip().lower()
        if not entity_id or entity_type not in ASSERTIVE_ENTITY_TYPES:
            continue

        name = str(raw.get("name") or "").strip()
        description = str(raw.get("description") or "").strip()
        canonical_text = _canonical_text(name, description)
        prop_key = proposition_key_for_claim(canonical_text)
        prop_id = proposition_id_for_key(prop_key)

        dedup_key = (entity_id, prop_id)
        if dedup_key in seen_pairs:
            continue
        seen_pairs.add(dedup_key)

        mapped.append(
            {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "prop_id": prop_id,
                "prop_key": prop_key,
                "canonical_text": canonical_text,
                "source_type": "textbook",
            }
        )

    return mapped
