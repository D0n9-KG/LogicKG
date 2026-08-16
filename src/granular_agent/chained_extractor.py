"""Phase 1: Chained extraction over the schema-guided DAG.

Each DAG node runs in a fresh LLM context (no conversation history). The
node receives its section text + a compact summary of what predecessor
nodes extracted + the schema fields it targets. It outputs atoms decorated
with evidence_span + confidence + discourse_role, plus a compact summary
that carries forward to dependents.

Adaptive fission: if a node's mean confidence < threshold, re-run that
node's fields split into two focused sub-calls (bounded by a per-paper
fission budget) instead of looping ReAct-style.
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.llm_client import call_llm, call_paratera, parse_json_response
from granular_agent.schema_manager import SchemaManager
from granular_agent.structure_mapper import topo_order, section_text_for_node
from granular_agent.grounding import attach_discourse_roles, ground_atoms
from granular_agent.gap_discovery import (detect_gaps_intra_node, score_gap,
                                          apply_schema_extension, validate_gap,
                                          recall_gap_probe)

FISSION_THRESHOLD = 0.40
MAX_FISSIONS_PER_PAPER = 2

EXTRACT_NODE_PROMPT = """You are extracting structured atoms from ONE section of a granular flow paper.

{schema_prompt}

This section's discourse role is: {discourse_role}.
You are responsible for these schema fields: {fields}.
Only emit atoms that belong to these fields and actually appear in this section. Do not invent.

Atom formats:
L1: {{"layer":"L1","entity_type":"...","entity":"...","evidence_span":"...","confidence":0.0-1.0}}
L2: {{"layer":"L2","relation":"...","subject":"...","object":"...","conditions":[...],"evidence_span":"...","confidence":0.0-1.0}}
L3 CONTRIBUTION: {{"layer":"L3","type":"CONTRIBUTION","statement":"...","subtypes":["..."],"params":[...],"evidence_span":"...","confidence":0.0-1.0}}
L3 CONTRIBUTION_RELATION: {{"layer":"L3","type":"CONTRIBUTION_RELATION","relation":"...","from":"...","to":"...","qualifier":"...","evidence_span":"...","confidence":0.0-1.0}}
L3 RESEARCH_QUESTION: {{"layer":"L3","type":"RESEARCH_QUESTION","statement":"...","evidence_span":"...","confidence":0.0-1.0}}
L3 CLOSURE: {{"layer":"L3","type":"CLOSURE","statement":"...","input_variables":[...],"output_variable":"...","function_form":"...","parameters":[...],"applicable_regime":"...","evidence_span":"...","confidence":0.0-1.0}}
PAPER: {{"layer":"PAPER","paper_type":"rheology|experiment|theory|DEM|review|other","evidence_span":"...","confidence":0.0-1.0}}

Rules:
- evidence_span MUST be a verbatim phrase copied from this section's text. Copy exactly, including symbols and units. This will be checked by exact string match; paraphrasing causes rejection.
- confidence is your self-assessed probability that this atom is correct AND the evidence_span is verbatim. Range 0.0-1.0.
- For L1 entity_type use ONLY schema enum values. If a type is missing, still extract the entity with the closest valid type and lower confidence.
- Multi-label subtypes on CONTRIBUTION (a finding can be both experimental_finding and mechanism_analysis).
- CONSTITUTIVE LAWS: if this section states or defines a constitutive relation / governing equation relating physical quantities (e.g. mu(I) = mu_s + (mu_2-mu_s)/(I_0/I + 1)), you MUST emit a CLOSURE atom with input_variables, output_variable, function_form (the equation text), and parameters (the named constants). Also emit MATERIAL_PARAMETER L1 atoms for each named fitted constant (e.g. mu_s, mu_2, I_0) and DIMENSIONLESS_NUMBER for dimensionless groups (e.g. I, I_0).
- BOUNDARY_CONDITION: emit for walls, rough sidewalls, periodic boundaries, shear direction, confining pressure setups. INITIAL_STATE: for packing fraction, density, sample preparation.
- CONTRIBUTION_RELATION (multi-mechanism competition): granular flow is a domain with COMPETING constitutive frameworks (μ(I) rheology vs non-local vs Coulomb plasticity vs viscoplastic). Actively look for and emit CONTRIBUTION_RELATION atoms capturing:
  * conflicts: when this paper's finding contradicts/limits a prior framework
  * extends/generalizes: when this paper extends a prior law to new regime
  * applies_in/applies_in_regime: the regime where a contribution holds
  * derives_from: when one contribution derives from another
  For Discussion/interpretation sections especially — papers routinely compare their results to prior work. Emit these relations even if implicit (e.g. "our model improves on the μ(I) law" → extends).
- Be thorough and exhaustive: a typical section contains 8-20 atoms. Enumerate EVERY distinct entity of the assigned types present in this section — every material, property, parameter, dimensionless number, boundary condition, device, measurement, numeric value. Do not stop at 3-5 atoms. For L1 entity atoms: extract each entity mention separately (do not merge "glass beads" and "particles" into one). For L2: connect measurements to the properties they measure. For L3: extract each distinct claim/contribution as its own atom.

{predecessor_context}

SECTION TEXT ({section_name}):
{section_text}

Output a JSON object:
{{"atoms": [...], "summary": "<=200 token compact summary of what you extracted, for the next section>"}}
Output ONLY the JSON object."""


class Blackboard:
    """JSON carrier: atoms extracted so far + per-node compact summaries."""

    def __init__(self):
        self.atoms: list[dict] = []
        self.summaries: dict[str, str] = {}  # node_id -> summary

    def add(self, node_id: str, atoms: list[dict], summary: str):
        for a in atoms:
            if isinstance(a, dict):
                a["_source_node"] = node_id
                self.atoms.append(a)
        self.summaries[node_id] = summary

    def predecessor_summary(self, deps: list[str]) -> str:
        if not deps:
            return ""
        parts = [f"[{d}] {self.summaries[d]}" for d in deps if d in self.summaries]
        return "Predecessor extracts:\n" + "\n".join(parts) if parts else ""

    def snapshot(self) -> dict:
        return {"atoms": list(self.atoms), "summaries": dict(self.summaries)}


def _call(prompt: str, llm: str, max_tokens: int = 8192) -> str | None:
    if llm == "deepseek":
        return call_llm(prompt, model="deepseek-chat", max_tokens=max_tokens)
    return call_paratera(prompt, model=llm, max_tokens=max_tokens)


def _parse_node_response(raw: str | None) -> tuple[list[dict], str]:
    if not raw:
        return [], ""
    parsed = parse_json_response(raw)
    if isinstance(parsed, dict):
        atoms = parsed.get("atoms", [])
        summary = parsed.get("summary", "")
        if isinstance(atoms, list):
            return atoms, summary or ""
    elif isinstance(parsed, list):
        return parsed, ""
    return [], ""


def _run_node(node: dict, sections: list, blocks: list, schema_prompt: str,
             blackboard: Blackboard, llm: str) -> tuple[list[dict], str]:
    """Execute one DAG node: build prompt, call LLM, return (atoms, summary)."""
    section_text = section_text_for_node(node, sections, blocks)
    if not section_text:
        return [], ""
    fields = node.get("fields", [])
    discourse_role = _discourse_for_node(node, sections)
    predecessor = blackboard.predecessor_summary(node.get("deps", []))
    prompt = EXTRACT_NODE_PROMPT.format(
        schema_prompt=schema_prompt,
        discourse_role=discourse_role,
        fields=", ".join(fields) if fields else "(unspecified)",
        predecessor_context=predecessor,
        section_name=node.get("section", ""),
        section_text=section_text,
    )
    raw = _call(prompt, llm)
    return _parse_node_response(raw)


def _discourse_for_node(node: dict, sections: list) -> str:
    sec = next((s for s in sections if s.get("name") == node.get("section")), None)
    return sec.get("discourse_role", "unknown") if sec else "unknown"


def _mean_confidence(atoms: list[dict]) -> float:
    confs = [float(a.get("confidence", 0.0) or 0.0) for a in atoms if isinstance(a, dict)]
    return sum(confs) / len(confs) if confs else 0.0


def _fission_fields(fields: list) -> tuple[list, list]:
    """Split a field list into two halves for focused re-extraction."""
    mid = max(1, len(fields) // 2)
    return fields[:mid], fields[mid:]


def extract_chained(structure_map: dict, blocks: list, schema_manager: SchemaManager,
                    llm: str = "deepseek", intra_dag_evolution: bool = False,
                    full_text: str = "", paper_id: str = "") -> dict:
    """Phase 1: run all DAG nodes in topological order with a shared blackboard.

    When intra_dag_evolution=True, schema evolution happens DURING extraction:
    after each node's atoms are extracted + per-node-grounded, gaps are detected,
    scored by intra-paper cross-node recurrence × discourse-role weight, validated
    with verbatim evidence, and—if accepted—the schema extends and DOWNSTREAM
    nodes re-fetch the schema prompt (forward propagation). This is the v2
    self-evolution design (docs/dataset-design/SELF-EVOLUTION-v2.md).

    Returns {atoms, blackboard, n_calls, fissions, gap_records, schema_evolutions}.
    """
    sections = structure_map.get("sections", [])
    dag = structure_map.get("dag", {"nodes": []})
    nodes = topo_order(dag)

    blackboard = Blackboard()
    n_calls = 0
    fissions = 0
    gap_records: list[dict] = []
    schema_evolutions: list[dict] = []
    schema_dirty = False

    for node in nodes:
        # Forward propagation: re-fetch schema prompt if a prior node extended the schema.
        if schema_dirty:
            schema_prompt = schema_manager.get_schema_prompt()
            schema_dirty = False
        else:
            schema_prompt = schema_manager.get_schema_prompt() if node is nodes[0] else schema_prompt

        atoms, summary = _run_node(node, sections, blocks, schema_prompt, blackboard, llm)
        n_calls += 1
        # Adaptive fission DISABLED: LLM self-confidence is uncalibrated and
        # uniformly high (0.85+), so the <0.40 threshold never triggered across
        # 49 papers (dead code). Re-enable with an objective signal (e.g. atom
        # density per section-length) if fission becomes needed. See SYSTEM-AUDIT.md #5/#7.
        fissions = 0

        # Intra-DAG evolution: per-node ground → detect gaps → score → validate → extend
        if intra_dag_evolution and full_text and atoms:
            role = _discourse_for_node(node, sections)
            atoms_tagged = attach_discourse_roles([a for a in atoms if isinstance(a, dict)], structure_map)
            atoms_tagged = ground_atoms(atoms_tagged, full_text)  # per-node grounding (idempotent with later Phase 2)
            node_gaps = detect_gaps_intra_node(atoms_tagged, schema_manager, node["id"], role)
            gap_records.extend(node_gaps)
            # Recall probe: LLM re-scans section for concepts needing a new slot
            # that enum-miss CANNOT see (silent extraction failure). 1 call/node.
            from granular_agent.structure_mapper import section_text_for_node
            sec_text = section_text_for_node(node, sections, blocks)
            recall_gaps = recall_gap_probe(sec_text, node.get("section", ""), role,
                                           atoms_tagged, schema_manager,
                                           paper_id or "intra", node["id"])
            n_calls += 1
            gap_records.extend(recall_gaps)
            all_node_gaps = node_gaps + recall_gaps
            for gap in all_node_gaps:
                s = score_gap(gap, gap_records)
                if not s["accept"]:
                    continue
                validated = validate_gap(gap, paper_id or "intra", schema_manager)
                n_calls += 1
                if not validated or not validated.get("valid"):
                    continue
                # Use validator's CORRECTED gap_type (not detector's proposal)
                corrected_gap = {"gap_type": validated.get("gap_type", gap.get("gap_type", "")),
                                 "value": gap.get("value", "")}
                new_ver = apply_schema_extension(schema_manager, corrected_gap, validated.get("evidence", ""), paper_id or "intra")
                if new_ver:
                    schema_evolutions.append({
                        "version": new_ver, "gap_type": corrected_gap["gap_type"], "value": gap.get("value"),
                        "evidence": validated.get("evidence", ""), "node_id": gap.get("node_id"),
                        "discourse_role": role, "cross_node": s["cross_node"], "score": s["score"],
                        "paper_id": paper_id,
                    })
                    schema_dirty = True  # downstream nodes will re-fetch the schema prompt

        blackboard.add(node["id"], atoms, summary)

    return {
        "atoms": blackboard.atoms,
        "blackboard": blackboard.snapshot(),
        "n_calls": n_calls,
        "fissions": fissions,
        "gap_records": gap_records,
        "schema_evolutions": schema_evolutions,
    }
