"""Gap discovery capability: passive + active gap discovery.

Passive: detect atoms that don't fit current schema (done in extractor).
Active: scan cross-paper recurring patterns not in schema.

This is one of our 3 true differences from RAGA.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.llm_client import call_llm, parse_json_response
from granular_agent.schema_manager import SchemaManager


def active_gap_scan(extraction_results: list[dict], schema_manager: SchemaManager,
                    min_recurrence: int = 3) -> list[dict]:
    """Active gap discovery: find recurring patterns across papers not in schema.

    Scans all extraction results for entity types / subtypes / relations that
    appear across multiple papers but are NOT in the current schema.
    Only candidates appearing in >= min_recurrence papers are returned.
    """
    entity_candidates = Counter()
    subtype_candidates = Counter()
    relation_candidates = Counter()

    valid_entities = set(t.upper() for t in schema_manager.get_entity_types())
    valid_subtypes = set(s.lower() for s in schema_manager.get_contribution_subtypes())
    valid_relations = set(r.lower() for r in schema_manager.get_relation_types())

    for result in extraction_results:
        paper_gaps = result.get("gaps", [])
        paper_id = result.get("paper_id", "")

        seen_in_paper = set()
        for gap in paper_gaps:
            gtype = gap.get("type")
            value = gap.get("value", "")
            key = f"{gtype}|{value}"

            if key in seen_in_paper:
                continue
            seen_in_paper.add(key)

            if "entity_type" in gtype:
                entity_candidates[value] += 1
            elif "subtype" in gtype:
                subtype_candidates[value] += 1
            elif "relation" in gtype:
                relation_candidates[value] += 1

    # Filter by min recurrence
    candidates = []
    for val, count in entity_candidates.most_common():
        if count >= min_recurrence and val not in valid_entities:
            candidates.append({
                "gap_type": "entity_type",
                "value": val,
                "recurrence": count,
                "papers": [r["paper_id"] for r in extraction_results
                          if any(g.get("value") == val for g in r.get("gaps", []))]
            })

    for val, count in subtype_candidates.most_common():
        if count >= min_recurrence and val.lower() not in valid_subtypes:
            candidates.append({
                "gap_type": "contribution_subtype",
                "value": val,
                "recurrence": count,
                "papers": [r["paper_id"] for r in extraction_results
                          if any(g.get("value") == val for g in r.get("gaps", []))]
            })

    for val, count in relation_candidates.most_common():
        if count >= min_recurrence and val.lower() not in valid_relations:
            candidates.append({
                "gap_type": "relation_type",
                "value": val,
                "recurrence": count,
                "papers": [r["paper_id"] for r in extraction_results
                          if any(g.get("value") == val for g in r.get("gaps", []))]
            })

    return candidates


def validate_gap(gap: dict, paper_id: str) -> dict | None:
    """Evidence-linked validation: does this gap have source-text evidence?

    Uses LLM to check if the gap candidate is a real concept that appears
    in the paper text and deserves a schema slot.
    """
    gap_type = gap.get("gap_type", "")
    value = gap.get("value", "")

    prompt = f"""A schema gap has been discovered. Validate whether it deserves to be added to the schema.

Gap type: {gap_type}
Candidate value: {value}
Recurrence: {gap.get('recurrence', 1)} papers

Questions:
1. Is "{value}" a legitimate scientific concept that would benefit from a dedicated schema slot?
2. Or is it a synonym/variant of an existing schema element?
3. Is it too vague or too specific to be useful?

Answer ONLY valid JSON:
{{"valid": true or false, "reason": "one short sentence", "suggested_alternative": "existing schema element if synonym, or empty"}}"""

    raw = call_llm(prompt, max_tokens=300)
    result = parse_json_response(raw)
    if not result or not isinstance(result, dict):
        return None

    return {
        "gap_type": gap_type,
        "value": value,
        "valid": result.get("valid", False),
        "reason": result.get("reason", ""),
        "suggested_alternative": result.get("suggested_alternative", ""),
        "evidence": f"Recurrence in {gap.get('recurrence', 1)} papers: {', '.join(gap.get('papers', [])[:5])}",
        "paper_id": paper_id,
    }
