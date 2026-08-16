"""QA generation capability: generate QA pairs from GROUNDED atoms.

Answers are anchored to a grounded atom's verbatim evidence_span (the same
span that Phase 2 exact-text-match verified against the full paper text).
This makes answer grounding deterministic by construction — the answer IS
a verbatim span, no separate LLM-judge grounding needed.

This is one of our 3 true differences from RAGA (which does QA retrieval on
existing questions; we GENERATE new QA pairs with paper-anchored answers).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.llm_client import call_llm, parse_json_response
from granular_agent.structure_mapper import load_paper_blocks, full_text_from_blocks

MINERU_BASE = "C:/Users/D0n9/Desktop/science_evo/data/upstream/remote_mineru/mineru_2355/papers"

# Max atoms to turn into QA (keeps the prompt bounded)
MAX_QA_ATOMS = 8

QA_PROMPT = """You are generating question-answer pairs for a benchmark, where each answer MUST be a verbatim phrase copied from the paper (given to you as the "answer_span"). Your job: write a question for which that exact span is the correct answer.

Rules:
- The question should be answerable SOLELY from the paper and have the given answer_span as a correct answer.
- Do NOT change the answer_span — it is verbatim from the paper and will be exact-match checked.
- Vary question type: for L1 entity atoms ask "what is X / what value / which material"; for L3 CONTRIBUTION ask "what does the paper claim about X"; for CLOSURE ask "what is the constitutive law / what are the parameters of X".
- One question per atom.

PAPER CONTEXT (for writing natural questions; the answer must still be the verbatim span, not a paraphrase from this context):
{context}

ATOMS (each with its verbatim answer_span):
{atoms_json}

Output ONLY a JSON array, one object per atom, in order:
[{{"question": "...", "answer": "<the verbatim answer_span, unchanged>", "atom_summary": "<one-line>", "layer": "L1|L2|L3", "atom_type": "<entity_type or contribution type or CLOSURE>"}}]
"""


def _select_qa_atoms(atoms: list[dict]) -> list[dict]:
    """Select a diverse, grounded subset for QA (prefer L1/L3/CLOSURE with non-empty spans)."""
    grounded = [a for a in atoms if isinstance(a, dict) and a.get("evidence_span")
                and a.get("grounded", True) is not False]
    # Diversify by layer/type
    picked = []
    seen_l1_type = set()
    # 2-3 L1 entities (one per entity_type)
    for a in grounded:
        if a.get("layer") == "L1" and a.get("entity_type") not in seen_l1_type:
            picked.append(a); seen_l1_type.add(a.get("entity_type"))
            if len([p for p in picked if p.get("layer") == "L1"]) >= 3:
                break
    # 2-3 L3 contributions
    for a in grounded:
        if a.get("layer") == "L3" and a.get("type") == "CONTRIBUTION":
            picked.append(a)
            if len([p for p in picked if p.get("layer") == "L3" and p.get("type") == "CONTRIBUTION"]) >= 3:
                break
    # 1 CLOSURE if present
    for a in grounded:
        if a.get("layer") == "L3" and a.get("type") == "CLOSURE":
            picked.append(a); break
    # 1 CONTRIBUTION_RELATION if present
    for a in grounded:
        if a.get("layer") == "L3" and a.get("type") == "CONTRIBUTION_RELATION":
            picked.append(a); break
    return picked[:MAX_QA_ATOMS]


def _atom_to_qa_input(a: dict) -> dict:
    """Compact atom description + its verbatim answer span, for the QA prompt."""
    layer = a.get("layer", "")
    if layer == "L1":
        desc = f"L1 entity ({a.get('entity_type','')}): {a.get('entity','')}"
    elif layer == "L3":
        t = a.get("type", "")
        if t == "CONTRIBUTION":
            desc = f"L3 CONTRIBUTION (subtypes={a.get('subtypes',[])}): {a.get('statement','')}"
        elif t == "CLOSURE":
            desc = f"L3 CLOSURE: {a.get('statement','')} (output={a.get('output_variable','')}, params={a.get('parameters',[])})"
        elif t == "CONTRIBUTION_RELATION":
            desc = f"L3 CONTRIBUTION_RELATION ({a.get('relation','')}): {a.get('from','')} -> {a.get('to','')}"
        else:
            desc = f"L3 {t}: {a.get('statement','')}"
    elif layer == "L2":
        desc = f"L2 relation ({a.get('relation','')}): {a.get('subject','')} -> {a.get('object','')}"
    else:
        desc = str(a)[:120]
    return {"desc": desc, "answer_span": a.get("evidence_span", "")}


def generate_qa(paper_id: str, atoms: list[dict]) -> list[dict]:
    """Generate QA pairs where each answer is a grounded atom's verbatim evidence_span.

    Grounding is deterministic by construction: the answer_span was already
    verified verbatim in the paper by Phase 2 exact-text-match. No LLM-judge
    grounding on the answer.
    """
    blocks = load_paper_blocks(paper_id)
    if not blocks:
        return []
    full_text = full_text_from_blocks(blocks)

    qa_atoms = _select_qa_atoms(atoms)
    if not qa_atoms:
        return []

    qa_inputs = [_atom_to_qa_input(a) for a in qa_atoms]
    # Context: first + last portion of full text (for natural question wording)
    ctx = full_text[:2500] + " ... " + full_text[-2500:] if len(full_text) > 5000 else full_text

    prompt = QA_PROMPT.format(
        context=ctx,
        atoms_json=json.dumps(qa_inputs, ensure_ascii=False),
    )
    raw = call_llm(prompt, model="deepseek-chat", max_tokens=2500)
    qa_pairs = parse_json_response(raw)
    if not isinstance(qa_pairs, list):
        return []

    # Two-layer post-check (breaks circularity with the extractor's evidence_span):
    # 1. answer verbatim in full_text (LLM compliance)
    # 2. answer SUPPORTS the atom it tests (token overlap with atom core value)
    # This makes QA test that the atom can actually answer a question about the
    # paper — not just that the LLM copied a span.
    from granular_agent.grounding import _normws, _supports, _tokens
    norm_full = _normws(full_text)
    verified = []
    for i, qa in enumerate(qa_pairs):
        if not isinstance(qa, dict):
            continue
        ans = qa.get("answer", "")
        in_text = bool(ans) and _normws(ans) in norm_full
        # find the atom this QA tests (by index alignment with qa_inputs)
        atom = qa_atoms[i] if i < len(qa_atoms) else None
        supported, reason = (True, "no-atom") if not atom else _supports(atom, ans)
        qa["paper_id"] = paper_id
        qa["in_text"] = in_text
        qa["supported"] = supported
        qa["support_reason"] = reason
        qa["grounded"] = in_text and supported  # now non-circular
        verified.append(qa)
    return verified
