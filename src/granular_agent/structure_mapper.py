"""Phase 0: Structure mapping.

Full-text-in, compact-structure-out. One LLM call reads the entire paper
and returns a discourse-role-tagged section structure + a schema-guided
DAG. The DAG nodes reference block indices (not char offsets) so the
chained extractor can slice the exact section text deterministically.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.llm_client import call_llm, parse_json_response

MINERU_BASE = "C:/Users/D0n9/Desktop/science_evo/data/upstream/remote_mineru/mineru_2355/papers"

# Discourse roles per Scientific Discourse Tagging (arXiv 1909.04758),
# restricted to the six the design doc specifies.
DISCOURSE_ROLES = ["summary", "context", "definition", "observation", "interpretation", "claim"]

# Schema fields a node may target. L1 entity types + L3 contribution subtypes
# + structural atoms. The structure mapper picks subsets of these per node.
SCHEMA_FIELDS = [
    "MATERIAL", "SAMPLE", "DEVICE", "NUMERIC", "UNIT", "PROPERTY", "MEASUREMENT",
    "BOUNDARY_CONDITION", "INITIAL_STATE", "MATERIAL_PARAMETER", "DIMENSIONLESS_NUMBER", "REGIME",
    "L2_RELATION", "CONTRIBUTION", "CONTRIBUTION_RELATION", "RESEARCH_QUESTION", "CLOSURE", "PAPER_TYPE",
]

STRUCTURE_PROMPT = """You are reading a full scientific paper from granular flow physics. Your job is ONLY to map its structure — do NOT extract atoms or facts.

The paper text is presented as numbered blocks. Each block begins with a tag like [§12] which is its block index. Block indices are contiguous integers starting at 0.

Output a JSON object with this exact shape:

{{
  "sections": [
    {{"name": "Abstract", "block_range": [0, 3], "discourse_role": "summary"}},
    {{"name": "Introduction", "block_range": [3, 9], "discourse_role": "context"}},
    {{"name": "Method", "block_range": [9, 18], "discourse_role": "definition"}},
    {{"name": "Results", "block_range": [18, 26], "discourse_role": "observation"}},
    {{"name": "Discussion", "block_range": [26, 30], "discourse_role": "interpretation"}},
    {{"name": "Conclusion", "block_range": [30, 35], "discourse_role": "claim"}}
  ],
  "key_entities": ["mu(I)", "shear rate", "inertial number", "glass beads"],
  "dag": {{
    "nodes": [
      {{"id": "n1", "section": "Method", "fields": ["MATERIAL", "BOUNDARY_CONDITION", "CLOSURE"], "deps": []}},
      {{"id": "n2", "section": "Results", "fields": ["MEASUREMENT", "NUMERIC", "CONTRIBUTION"], "deps": ["n1"]}},
      {{"id": "n3", "section": "Discussion", "fields": ["CONTRIBUTION", "CONTRIBUTION_RELATION"], "deps": ["n1", "n2"]}},
      {{"id": "n4", "section": "Conclusion", "fields": ["RESEARCH_QUESTION", "CONTRIBUTION"], "deps": ["n3"]}}
    ]
  }}
}}

Rules:
- sections[].block_range is [start_block_index, end_block_index) — a half-open interval of block indices. Every content block must belong to exactly one section. Merge small/adjacent blocks rather than emitting 30 sections; aim for 4-8 sections. Skip reference/acknowledgment blocks by NOT including them in any section.
- discourse_role MUST be one of: {roles}.
- Each dag node targets one section and a subset of schema fields from: {fields}.
- CRITICAL: EVERY non-reference section MUST appear in at least one DAG node. Do not skip Abstract, Introduction, or Conclusion — these carry headline contributions, research questions, and final claims. A typical DAG has 5-8 nodes (one per section, sometimes two for a long Method/Results).
- Suggested field assignments by discourse role:
  * summary (Abstract): CONTRIBUTION, MATERIAL, DIMENSIONLESS_NUMBER, PAPER_TYPE
  * context (Introduction): RESEARCH_QUESTION, MATERIAL, CONTRIBUTION
  * definition (Method): MATERIAL, BOUNDARY_CONDITION, INITIAL_STATE, MATERIAL_PARAMETER, CLOSURE, DEVICE
  * observation (Results): MEASUREMENT, NUMERIC, PROPERTY, CONTRIBUTION, L2_RELATION
  * interpretation (Discussion): CONTRIBUTION, CONTRIBUTION_RELATION, MECHANISM_ANALYSIS-equivalent (use CONTRIBUTION)
  * claim (Conclusion): CONTRIBUTION, RESEARCH_QUESTION, CONTRIBUTION_RELATION
- deps lists earlier node ids whose atoms this node needs as context (e.g. Results depends on Method's definitions, Discussion depends on Results' observations, Conclusion depends on Discussion).
- The DAG must be acyclic. Order nodes so deps come first.
- sections must cover every content block index from 0 to the last content block (references excluded). If a block is reference/acknowledgment, leave it out of all sections.
- Keep this output compact. Do not include the atoms — that is a later phase.

PAPER BLOCKS:
{blocks}"""


def load_paper_blocks(paper_id: str) -> list[dict]:
    """Load paper text as a list of {index, char_start, char_end, text} blocks.

    No truncation. Block boundaries come from mineru content_list.json.
    Reference-like blocks (short, start with [digit]) are skipped so they
    do not pollute char ranges or block indices.
    """
    p = os.path.join(MINERU_BASE, paper_id, "content_list.json")
    if not os.path.isfile(p):
        return []
    cl = json.load(open(p, encoding="utf-8"))
    blocks = []
    cursor = 0
    for it in cl:
        if it.get("type") != "text" or not it.get("text"):
            continue
        t = it["text"].strip()
        if len(t) < 10:
            continue
        # Skip reference-like blocks: "[12] Smith et al. ..."
        if t.startswith("[") and any(c.isdigit() for c in t[:5]):
            continue
        end = cursor + len(t)
        blocks.append({"index": len(blocks), "char_start": cursor, "char_end": end, "text": t})
        cursor = end + 1  # +1 for the joining space
    return blocks


def blocks_to_indexed_text(blocks: list[dict]) -> str:
    """Render blocks as one string with [§index] markers at each block start."""
    out = []
    for b in blocks:
        out.append(f"[§{b['index']}] {b['text']}")
    return "\n\n".join(out)


def full_text_from_blocks(blocks: list[dict]) -> str:
    """Plain joined text (no markers). Used by grounding for exact-match."""
    return " ".join(b["text"] for b in blocks)


def slice_blocks(blocks: list[dict], start: int, end: int) -> str:
    """Return joined text for blocks in [start, end) index range."""
    sel = [b for b in blocks if start <= b["index"] < end]
    return " ".join(b["text"] for b in sel)


def map_structure(paper_id: str, blocks: list[dict], llm: str = "deepseek") -> dict | None:
    """Phase 0: one LLM call over the full paper → structure map.

    Returns {sections, key_entities, dag} or None on failure.
    """
    if not blocks:
        return None
    text = blocks_to_indexed_text(blocks)
    prompt = STRUCTURE_PROMPT.format(
        roles=", ".join(DISCOURSE_ROLES),
        fields=", ".join(SCHEMA_FIELDS),
        blocks=text,
    )
    raw = call_llm(prompt, model="deepseek-chat", max_tokens=4096) if llm == "deepseek" \
        else _call_paratera_structure(prompt)
    if not raw:
        return None
    parsed = parse_json_response(raw)
    if not isinstance(parsed, dict):
        return None
    # Normalize: ensure sections cover all blocks; clamp block_ranges.
    parsed = _normalize_structure(parsed, len(blocks))
    return parsed


def _call_paratera_structure(prompt: str) -> str | None:
    from granular_agent.llm_client import call_paratera
    return call_paratera(prompt, model="Kimi-K2.6", max_tokens=4096)


def _normalize_structure(smap: dict, n_blocks: int) -> dict:
    """Clamp block ranges, drop empty sections, ensure DAG node ids are strings."""
    sections = smap.get("sections", [])
    for s in sections:
        br = s.get("block_range", [0, 0])
        if not (isinstance(br, list) and len(br) == 2):
            continue
        a, b = br[0], br[1]
        a = max(0, int(a)); b = max(a, int(b))
        if b > n_blocks:
            b = n_blocks
        s["block_range"] = [a, b]
    # Drop sections with empty range
    smap["sections"] = [s for s in sections if s.get("block_range", [0, 0])[1] > s.get("block_range", [0, 0])[0]]
    dag = smap.get("dag", {})
    for n in dag.get("nodes", []):
        if "id" in n:
            n["id"] = str(n["id"])
        n["deps"] = [str(d) for d in n.get("deps", [])]
    return smap


def topo_order(dag: dict) -> list[dict]:
    """Return DAG nodes in topological order (deps before dependents)."""
    nodes = dag.get("nodes", [])
    by_id = {n["id"]: n for n in nodes}
    visited = []
    temp_mark = set()
    done = set()

    def visit(nid: str):
        if nid in done:
            return
        if nid in temp_mark:
            return  # cycle — skip edge
        temp_mark.add(nid)
        for d in by_id.get(nid, {}).get("deps", []):
            visit(d)
        temp_mark.discard(nid)
        done.add(nid)
        visited.append(by_id[nid])

    for n in nodes:
        visit(n["id"])
    return visited


def section_text_for_node(node: dict, sections: list[dict], blocks: list[dict]) -> str:
    """Look up the node's section and return its sliced block text."""
    sec_name = node.get("section")
    sec = next((s for s in sections if s.get("name") == sec_name), None)
    if not sec:
        return ""
    a, b = sec.get("block_range", [0, 0])
    return slice_blocks(blocks, a, b)
