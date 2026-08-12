"""QA generation capability: generate QA pairs from extracted atoms.

Answers are anchored to paper experimental data, not LLM-fabricated.
This is one of our 3 true differences from RAGA (which does QA retrieval, not generation).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.llm_client import call_llm, parse_json_response

MINERU_BASE = "C:/Users/D0n9/Desktop/science_evo/data/upstream/remote_mineru/mineru_2355/papers"

QA_PROMPT = """Based on the extracted atoms from a scientific paper, generate QA pairs for evaluation.

Rules:
- Questions should test whether the extraction correctly captured the paper's content.
- Answers must be grounded in the paper text — do NOT fabricate answers.
- For each QA pair, provide the question, the expected answer (from paper text), and which atom it tests.
- Generate 3-5 QA pairs covering different layers (L1 entities, L3 contributions).

EXTRACTED ATOMS (JSON):
{atoms}

PAPER TEXT (excerpt):
{text}

Output ONLY a JSON array of QA pairs:
[{{"question": "...", "answer": "...", "tests_atom": "brief description of which atom this tests", "layer": "L1|L3"}}]"""


def load_paper_text(paper_id: str, max_chars: int = 6000) -> str:
    p = os.path.join(MINERU_BASE, paper_id, "content_list.json")
    if not os.path.isfile(p):
        return ""
    cl = json.load(open(p, encoding="utf-8"))
    return " ".join(it.get("text", "") for it in cl if it.get("type") == "text")[:max_chars]


def generate_qa(paper_id: str, atoms: list[dict]) -> list[dict]:
    """Generate QA pairs from extracted atoms. Answers anchored to paper text."""
    text = load_paper_text(paper_id)
    if not text:
        return []

    # Summarize atoms for the prompt (avoid token overflow)
    atom_summary = []
    for a in atoms:
        if not isinstance(a, dict):
            continue
        if a.get("layer") == "L1":
            atom_summary.append({"layer": "L1", "entity_type": a.get("entity_type"), "entity": a.get("entity", "")[:80]})
        elif a.get("layer") == "L3":
            atom_summary.append({"layer": "L3", "type": a.get("type"), "statement": a.get("statement", "")[:120], "subtypes": a.get("subtypes", [])})
        elif a.get("layer") == "L2":
            atom_summary.append({"layer": "L2", "relation": a.get("relation"), "subject": a.get("subject", "")[:50], "object": a.get("object", "")[:50]})

    prompt = QA_PROMPT.format(
        atoms=json.dumps(atom_summary[:30], ensure_ascii=False),
        text=text
    )
    raw = call_llm(prompt, max_tokens=2000)
    qa_pairs = parse_json_response(raw)
    return qa_pairs if isinstance(qa_pairs, list) else []
