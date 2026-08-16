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


def detect_gaps_intra_node(atoms: list[dict], schema_manager: SchemaManager,
                          node_id: str, discourse_role: str) -> list[dict]:
    """Per-node gap detection for intra-DAG evolution.

    Returns gaps tagged with node_id + discourse_role + the triggering atom's
    verbatim evidence_span. Reuses the same enum-miss logic as Extractor._detect_gaps
    but operates on one node's atoms and adds topology/role context.
    """
    gaps = []
    valid_entities = set(t.upper() for t in schema_manager.get_entity_types())
    valid_subtypes = set(s.lower() for s in schema_manager.get_contribution_subtypes())
    valid_relations = set(r.lower() for r in schema_manager.get_relation_types())

    for atom in atoms:
        if not isinstance(atom, dict):
            continue
        ev = atom.get("evidence_span", "") or ""
        if atom.get("layer") == "L1":
            et = atom.get("entity_type", "").upper()
            if et and et not in valid_entities:
                gaps.append({"gap_type": "entity_type", "value": et, "atom": atom,
                             "node_id": node_id, "discourse_role": discourse_role,
                             "evidence_span": ev})
        elif atom.get("layer") == "L3" and atom.get("type") == "CONTRIBUTION":
            for st in atom.get("subtypes", []):
                if st.lower() not in valid_subtypes:
                    gaps.append({"gap_type": "contribution_subtype", "value": st, "atom": atom,
                                 "node_id": node_id, "discourse_role": discourse_role,
                                 "evidence_span": ev})
        elif atom.get("layer") == "L3" and atom.get("type") == "CONTRIBUTION_RELATION":
            rel = atom.get("relation", "").lower()
            if rel and rel not in valid_relations:
                gaps.append({"gap_type": "relation_type", "value": rel, "atom": atom,
                             "node_id": node_id, "discourse_role": discourse_role,
                             "evidence_span": ev})
    return gaps


# Discourse-role weights for gap scoring (definition sections introduce terms
# that should be schema slots; observation sections mostly yield instance noise).
DISCOURSE_WEIGHT = {
    "definition": 1.5, "summary": 1.2, "claim": 1.2,
    "interpretation": 1.0, "context": 1.0, "observation": 0.7,
}


def score_gap(gap: dict, gap_records: list[dict]) -> dict:
    """Score a gap by intra-paper cross-node recurrence × discourse weight.

    cross_node_count = how many DISTINCT prior+current nodes saw the same
    (gap_type, value). A gap appearing in ≥2 nodes is a strong intra-paper
    signal (no need to wait for cross-paper recurrence).
    """
    gtype = gap.get("gap_type", "")
    value = (gap.get("value", "") or "").lower()
    role = gap.get("discourse_role", "context")
    weight = DISCOURSE_WEIGHT.get(role, 1.0)

    cross_node = 1  # this node
    seen_nodes = {gap.get("node_id")}
    for g in gap_records:
        if g.get("gap_type") == gtype and (g.get("value", "") or "").lower() == value:
            if g.get("node_id") not in seen_nodes:
                seen_nodes.add(g.get("node_id"))
                cross_node += 1

    has_evidence = bool(gap.get("evidence_span", "").strip())
    score = cross_node * weight
    # Gate: any gap with a verbatim evidence span is sent to validate_gap (the
    # LLM+evidence gate). cross_node and discourse_role are SCORING METADATA
    # (reported with each extension), NOT gates — this lets forward propagation
    # fire during extraction. The design doc's stricter threshold can be
    # re-enabled for a sensitivity ablation.
    accept = has_evidence
    return {"score": round(score, 2), "cross_node": cross_node, "weight": weight,
            "accept": accept, "has_evidence": has_evidence}


def apply_schema_extension(schema_manager: SchemaManager, gap: dict, evidence: str,
                            paper_id: str) -> str | None:
    """Extend the schema per gap type. Returns new version string or None."""
    gtype = gap.get("gap_type", "")
    value = gap.get("value", "")
    if gtype == "entity_type":
        return schema_manager.extend_entity_type(value, evidence, paper_id)
    if gtype == "contribution_subtype":
        return schema_manager.extend_contribution_subtype(value, evidence, paper_id)
    if gtype == "relation_type":
        return schema_manager.extend_relation_type(value, evidence, paper_id)
    return None


RECALL_PROBE_PROMPT = """You are auditing whether an extraction missed content. Given a paper section and the atoms already extracted from it, identify CONCEPTS present in the section that SHOULD be atoms but were NOT extracted, and that do NOT fit the current schema (i.e. they need a new schema slot, not just more extraction).

Current schema:
- L1 entity types: {entities}
- L3 contribution subtypes: {subtypes}
- L3 contribution relations: {relations}

Atoms already extracted from this section (do not re-list these):
{existing}

SECTION TEXT ({section_name}, discourse role: {role}):
{section_text}

For each missing concept that needs a NEW schema slot (not just better extraction of an existing type), output:
- value: the concept name
- gap_type: entity_type | contribution_subtype | relation_type (which schema dimension it needs)
- evidence_span: a verbatim phrase from the section proving this concept exists and needs a slot

If the section has no such missing-concept-needing-new-slot, output an empty array. Do NOT list concepts already covered by the existing types above — only ones that genuinely don't fit.

Output ONLY a JSON array:
[{{"value":"...","gap_type":"...","evidence_span":"..."}}]"""


def recall_gap_probe(section_text: str, section_name: str, discourse_role: str,
                     existing_atoms: list[dict], schema_manager: SchemaManager,
                     paper_id: str, node_id: str) -> list[dict]:
    """Active recall probe: LLM scans a section for concepts that need a NEW
    schema slot but were not extracted. This is the detector the enum-miss
    check CANNOT do — it finds gaps even when the LLM produced no out-of-enum
    atom (i.e. it silently failed to extract a concept the schema can't hold).

    One LLM call per section. Returns gaps tagged with node_id + evidence_span.
    """
    if not section_text.strip():
        return []
    from granular_agent.llm_client import call_llm, parse_json_response
    entities = ", ".join(schema_manager.get_entity_types())
    subtypes = ", ".join(schema_manager.get_contribution_subtypes())
    relations = ", ".join(schema_manager.get_relation_types())
    # Summarize existing atoms compactly
    existing = []
    for a in existing_atoms[:30]:
        if not isinstance(a, dict):
            continue
        if a.get("layer") == "L1":
            existing.append(f"L1 {a.get('entity_type')}: {a.get('entity','')[:50]}")
        elif a.get("layer") == "L3":
            existing.append(f"L3 {a.get('type')}: {str(a.get('statement',''))[:60]}")
    existing_str = "\n".join(existing) if existing else "(none)"

    prompt = RECALL_PROBE_PROMPT.format(
        entities=entities, subtypes=subtypes, relations=relations,
        existing=existing_str, section_name=section_name, role=discourse_role,
        section_text=section_text[:6000],  # cap section text per probe
    )
    raw = call_llm(prompt, max_tokens=1500)
    parsed = parse_json_response(raw)
    if not isinstance(parsed, list):
        return []
    gaps = []
    for g in parsed:
        if not isinstance(g, dict):
            continue
        gaps.append({
            "gap_type": g.get("gap_type", ""),
            "value": g.get("value", ""),
            "evidence_span": g.get("evidence_span", ""),
            "node_id": node_id,
            "discourse_role": discourse_role,
            "paper_id": paper_id,
            "probe": "recall",
        })
    return gaps


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


def validate_gap(gap: dict, paper_id: str, schema_manager: SchemaManager | None = None,
                 domain: str = "granular flow physics") -> dict | None:
    """Evidence-anchored validation: does this gap's verbatim source span support
    a new schema slot?

    The validator receives the triggering atom's evidence_span (verbatim text
    from the paper), NOT a recurrence count. This makes "evidence-linked
    validation" literal: the LLM sees the actual source text and judges whether
    it denotes a distinct scientific category absent from the current schema.
    Domain-agnostic (no hardcoded entity lists).
    """
    gap_type = gap.get("gap_type", gap.get("type", ""))
    value = gap.get("value", "")
    atom = gap.get("atom", {}) or {}
    # Recall-probe gaps carry evidence_span directly on the gap (no atom);
    # enum-miss gaps carry it on the atom. Check both.
    evidence_span = (gap.get("evidence_span", "") or atom.get("evidence_span", "")
                     or atom.get("evidence", ""))
    # Gate: no verbatim evidence → reject (prevents probe from fabricating slots)
    if not evidence_span.strip():
        return {"gap_type": gap_type, "value": value, "valid": False,
                "reason": "no verbatim evidence span provided", "evidence": "",
                "paper_id": paper_id}

    # Current schema (for "distinct from existing?" judgment)
    if schema_manager is not None:
        cur_entity_list = schema_manager.get_entity_types()
        cur_subtype_list = schema_manager.get_contribution_subtypes()
        cur_relation_list = schema_manager.get_relation_types()
        cur_entities = ", ".join(cur_entity_list)
        cur_subtypes = ", ".join(cur_subtype_list)
        cur_relations = ", ".join(cur_relation_list)
    else:
        cur_entity_list = cur_subtype_list = cur_relation_list = []
        cur_entities = cur_subtypes = cur_relations = "(unavailable)"

    # Deterministic near-duplicate gate (non-LLM): reject if candidate is
    # token-overlap >=0.7 with an existing enum value in the SAME dimension.
    # This prevents bloat like "surface tension" added as entity_type when
    # PROPERTY already covers it (LLM judge was too loose).
    from granular_agent.grounding import _tokens
    val_tokens = _tokens(value)
    if val_tokens:
        existing_in_dim = {"entity_type": cur_entity_list, "contribution_subtype": cur_subtype_list,
                           "relation_type": cur_relation_list}.get(gap_type, [])
        for ex in existing_in_dim:
            ex_tokens = _tokens(ex)
            if not ex_tokens:
                continue
            overlap = len(val_tokens & ex_tokens) / max(1, len(val_tokens | ex_tokens))
            if overlap >= 0.5:
                return {"gap_type": gap_type, "value": value, "valid": False,
                        "reason": f"near-duplicate of existing '{ex}' (overlap {overlap:.2f})",
                        "evidence": evidence_span, "suggested_alternative": ex,
                        "paper_id": paper_id}

    evidence_block = (
        f"VERBATIM SOURCE SPAN (from the paper that triggered this gap):\n\"{evidence_span}\""
        if evidence_span else
        "VERBATIM SOURCE SPAN: (none — recurrence-only gap)"
    )

    prompt = f"""A schema gap was detected during extraction from a {domain} paper. Validate whether it should be added to the schema.

Gap type proposed by detector: {gap_type}
Candidate value: "{value}"
{evidence_block}

Current schema:
- L1 entity types: {cur_entities}
- L3 contribution subtypes: {cur_subtypes}
- L3 contribution relations: {cur_relations}

Validation criteria (answer each):
1. Does the verbatim source span above actually denote the category "{value}"? If the span doesn't mention or support "{value}", REJECT.
2. Is "{value}" a DISTINCT category not already covered by the existing types listed above? (check synonyms/near-duplicates). If near-duplicate of existing, REJECT and suggest the existing one.
3. CORRECT DIMENSION: which schema dimension does "{value}" genuinely belong to?
   - entity_type: a physical object/quantity/measure that gets mentioned (MATERIAL, PROPERTY, etc.)
   - contribution_subtype: a TYPE of contribution/findings (what the paper CONTRIBUTES — a finding type)
   - relation_type: a relation BETWEEN contributions (supports/conflicts/extends)
   A phenomenon/process (e.g. "shear band", "hysteresis") is usually NOT an entity_type — if it's a finding, it belongs in contribution_subtype; if it's a process, it may not need a slot. If "{value}" doesn't fit any dimension well, REJECT.
4. Would adding it improve extraction coverage, or does it risk bloat (too specific / paper-specific)?

If the span supports "{value}" as a distinct, generalizable new slot in the CORRECT dimension, accept with that dimension. Otherwise reject.

Answer ONLY valid JSON:
{{"valid": true or false, "correct_gap_type": "entity_type"|"contribution_subtype"|"relation_type"|"", "reason": "one short sentence citing the span and the dimension judgment", "suggested_alternative": "existing type if duplicate, or empty string"}}"""

    raw = call_llm(prompt, max_tokens=400)
    result = parse_json_response(raw)
    if not result or not isinstance(result, dict):
        return None

    # Use the validator's corrected dimension if provided and valid
    corrected = result.get("correct_gap_type", "")
    if corrected not in ("entity_type", "contribution_subtype", "relation_type"):
        corrected = gap_type  # fall back to detector's proposal
    return {
        "gap_type": corrected,
        "value": value,
        "valid": result.get("valid", False),
        "reason": result.get("reason", ""),
        "suggested_alternative": result.get("suggested_alternative", ""),
        "evidence": evidence_span,
        "paper_id": paper_id,
    }
