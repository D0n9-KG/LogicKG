"""Downstream QA generation from an extracted instance hypergraph (C3 minimal:
downstream QA reflects extraction quality). Each hyperedge becomes a QA pair
whose answer is anchored to the hyperedge's verbatim evidence_span — so the
QA is self-verifiable (the span must appear verbatim in the paper text, no
gold annotation needed). This is the extraction->downstream link: a hyperedge
that cannot ground a QA is a weak extraction.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.hypergraph_schema import InstanceHypergraph, Hyperedge, HGNode


def _node_text(nid: str, instance: InstanceHypergraph) -> str:
    n = instance.nodes.get(nid)
    return n.surface if n else nid


def generate_hg_qa(instance: InstanceHypergraph) -> list[dict]:
    """Generate one QA per hyperedge. answer carries the evidence_span +
    qualifier values; the question references the connected nodes."""
    qa = []
    for he in instance.hyperedges.values():
        nodes = [_node_text(nid, instance) for nid in he.node_ids]
        q, a = _qa_for_pattern(he, nodes)
        if not q:
            continue
        qa.append({
            "paper_id": instance.paper_id,
            "eid": he.eid,
            "pattern_type": he.pattern_type,
            "question": q,
            "answer": a,
            "evidence_span": he.evidence_span,
            "qualifiers": he.qualifiers,
        })
    return qa


def _qa_for_pattern(he: Hyperedge, nodes: list[str]) -> tuple[str, str]:
    """Build a (question, answer) by pattern_type. Answer is grounded in the
    evidence_span + qualifiers (no fabrication)."""
    ev = he.evidence_span
    quals = he.qualifiers
    role_node = dict(zip(he.node_roles, nodes))
    if he.pattern_type == "constitutive_law" or "constitutive" in he.pattern_type:
        out = role_node.get("output", nodes[0] if nodes else "")
        inp = role_node.get("input", nodes[1] if len(nodes) > 1 else "")
        ff = quals.get("function_form", "")
        a = (f"The constitutive relation {out} = f({inp})" + (f" with form {ff}" if ff else "")
             + f'. Evidence: "{ev}"')
        return f"What is the constitutive relation between {out} and {inp}?", a
    if he.pattern_type == "measures":
        inst = role_node.get("instrument", nodes[0] if nodes else "")
        obj = role_node.get("object", nodes[1] if len(nodes) > 1 else "")
        return f"What does {inst} measure?", f"{inst} measures {obj}. Evidence: \"{ev}\""
    if he.pattern_type == "claim_relation":
        frm = role_node.get("from", nodes[0] if nodes else "")
        to = role_node.get("to", nodes[1] if len(nodes) > 1 else "")
        rel = quals.get("relation_type", he.pattern_type)
        return f"What is the relation between {frm} and {to}?", f"{rel} (evidence: \"{ev}\")"
    # generic / evolved patterns: surface the connected nodes + qualifiers
    nodes_str = ", ".join(f"{r}={n}" for r, n in zip(he.node_roles, nodes))
    a = f"The paper states a {he.pattern_type} relating {nodes_str}. Evidence: \"{ev}\""
    return f"What relation does the paper state among: {nodes_str}?", a


def _norm_for_match(s: str) -> str:
    """Normalize a string for verbatim-substring grounding: NFKC (folds
    compatibility chars / wide→narrow), strip combining marks (MinerU OCR
    mangles math symbols into combining sequences that differ run-to-run),
    collapse whitespace. Both the evidence_span and the full_text are
    normalized so a real verbatim span matches despite re-encoding variance.
    Without this, equation-heavy papers (C9726/5022) false-negative at 0.54
    — diagnosed as an audit-tool artifact, not extraction loss."""
    import unicodedata, re
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    # strip combining marks (Mn) — OCR-mangled math often appends stray marks
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def verify_qa_grounding(qa_pairs: list[dict], full_text: str,
                        blocks: list[dict] | None = None) -> dict:
    """Self-verification: every answer's evidence_span MUST appear verbatim in
    the paper text. Returns how many are grounded (in_text). This is the
    reference-free quality probe — ungrounded QA = weak extraction.

    Both sides are NFKC + combining-mark + whitespace normalized so equation/
    OCR-encoding variance (the false-negative on C9726/5022) doesn't under-
    count real verbatim spans.

    If `blocks` is given, also ground against each raw mineru block's text
    individually. This removes the join artifact: full_text_from_blocks
    inserts a space between blocks, which breaks a verbatim span that was
    captured inside one block whose trailing/boundary whitespace doesn't
    match the join separator (the Bagnold-sentence false-negative on C9726).
    Grounding against the raw block the evidence was actually drawn from is
    the correct measurement of extraction quality, decoupled from join
    formatting."""
    ft_n = _norm_for_match(full_text)
    block_ns = [_norm_for_match(b.get("text", "")) for b in blocks] if blocks else []
    grounded = 0
    for q in qa_pairs:
        ev = _norm_for_match(q.get("evidence_span", ""))
        if not ev:
            continue
        if ev in ft_n:
            grounded += 1
            continue
        # join artifact: check each raw block individually
        if any(ev in bn for bn in block_ns):
            grounded += 1
    return {"n_qa": len(qa_pairs), "n_grounded": grounded,
            "grounding_rate": round(grounded / max(1, len(qa_pairs)), 3)}


if __name__ == "__main__":
    import json
    inst_path = sys.argv[1] if len(sys.argv) > 1 else \
        ".research_tmp/hg_out/PPR_00180B90C8D8_instance.json"
    d = json.load(open(inst_path, encoding="utf-8"))
    inst = InstanceHypergraph(paper_id=d.get("paper_id", ""))
    for nid, n in d.get("nodes", {}).items():
        from granular_agent.hypergraph_schema import HGNode
        inst.add_node(HGNode(nid=nid, labels=n.get("labels", []),
                             surface=n.get("surface", ""),
                             properties=n.get("properties", {}),
                             evidence_span=n.get("evidence_span", "")))
    for eid, h in d.get("hyperedges", {}).items():
        inst.add_hyperedge(Hyperedge(eid=eid, pattern_type=h.get("pattern_type", ""),
                                      node_ids=h.get("node_ids", []),
                                      node_roles=h.get("node_roles", []),
                                      qualifiers=h.get("qualifiers", {}),
                                      evidence_span=h.get("evidence_span", "")))
    qa = generate_hg_qa(inst)
    print(f"generated {len(qa)} QA from {len(inst.hyperedges)} hyperedges")
    # load full text for grounding verification
    from granular_agent.structure_mapper import load_paper_blocks, full_text_from_blocks
    ft = full_text_from_blocks(load_paper_blocks(inst.paper_id)) if inst.paper_id else ""
    v = verify_qa_grounding(qa, ft)
    print(f"grounding: {v['n_grounded']}/{v['n_qa']} ({v['grounding_rate']}) evidence spans verbatim in paper")
    print("\nsample QA (first 6):")
    for q in qa[:6]:
        print(f"  [{q['pattern_type']}] Q: {q['question'][:90]}")
        print(f"            A: {q['answer'][:110]}")
