"""Phase 2: Grounding, rebind detection, lookup.

Grounding is deterministic (no LLM): each atom's evidence_span must appear
verbatim in the paper text. Whitespace is normalized before matching so
wrapped lines and extra spaces don't cause false negatives.

Rebind detection finds candidate semantic-rebinding cases deterministically:
the same entity surface form appearing under different discourse roles
(e.g. defined in Method, then re-used in Conclusion) — flagged for the
LLM lookup pass to judge, not asserted as hallucination.

Lookup re-reads the relevant section for low-confidence or ungrounded
atoms in one LLM call and either upgrades or discards them.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.llm_client import call_llm, call_paratera, parse_json_response

# Roles where an entity is being DEFINED (its binding is fixed).
DEFINITION_ROLES = {"definition"}


def _normws(s: str | None) -> str:
    """Normalize whitespace: collapse runs to single space, strip, lowercase."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip().lower()


def _tokens(s: str) -> set[str]:
    """Tokenize for fuzzy matching: lowercase, strip LaTeX/punctuation, split on whitespace/underscore."""
    if not s:
        return set()
    # remove LaTeX commands \tilde{z} -> z, \mu -> mu, $...$
    s = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', s)  # \tilde{z} -> z
    s = re.sub(r'\\[a-zA-Z]+', ' ', s)  # \mu -> space
    s = re.sub(r'[\$\\{}]', ' ', s)
    s = re.sub(r'[^a-zA-Z0-9\s]', ' ', s)  # underscore/hyphen -> space (so surface_tension == surface tension)
    toks = set(s.lower().split())
    return {t for t in toks if len(t) > 1 or t in ('i',)}  # keep single-letter physics vars like I


def _atom_core_values(a: dict) -> list[str]:
    """The core content strings an evidence_span MUST mention to actually
    support this atom (breaks the circular 'span in text' check)."""
    layer = a.get("layer")
    vals = []
    if layer == "L1":
        v = a.get("entity", "")
        if v:
            vals.append(v)
    elif layer == "L2":
        for k in ("subject", "object"):
            v = a.get(k, "")
            if v:
                vals.append(v)
    elif layer == "L3":
        t = a.get("type")
        if t == "CONTRIBUTION":
            st = a.get("statement", "")
            if st:
                vals.append(st[:80])
        elif t == "CONTRIBUTION_RELATION":
            for k in ("from", "to"):
                v = a.get(k, "")
                if v:
                    vals.append(v)
        elif t == "CLOSURE":
            for k in ("output_variable", "function_form"):
                v = a.get(k, "")
                if v:
                    vals.append(v)
            for p in a.get("parameters", []) or []:
                vals.append(p)
        elif t == "RESEARCH_QUESTION":
            st = a.get("statement", "")
            if st:
                vals.append(st[:80])
    elif layer == "PAPER":
        return []
    return vals


def _supports(atom: dict, evidence_span: str) -> tuple[bool, str]:
    """Check if the evidence_span actually SUPPORTS the atom (not just 'in text').

    Token-set overlap (Jaccard) tolerates word-order/inflection/LaTeX form
    differences — "flowing layer thickness" vs "thickness of the flowing layer"
    both tokenize to overlapping sets. This breaks the circular
    'evidence_span is LLM-copied so it's in text' check: the span must be
    ABOUT the atom (its core tokens must appear), not just present in the paper.
    """
    vals = _atom_core_values(atom)
    if not vals:
        return True, "no-core-value"
    ev_tokens = _tokens(evidence_span)
    if not ev_tokens:
        return False, "empty-span"
    unsupported = []
    for v in vals:
        v_tokens = _tokens(v)
        if not v_tokens:
            continue
        # Jaccard overlap of token sets (order-independent, inflection-tolerant)
        overlap = len(ev_tokens & v_tokens) / len(v_tokens)
        # Require >=50% of core-value tokens to appear in the span
        if overlap < 0.5:
            unsupported.append(f"low-overlap({overlap:.2f}):{v[:30]}")
    if unsupported:
        return False, "; ".join(unsupported[:3])
    return True, "supported"


def ground_atoms(atoms: list[dict], full_text: str) -> list[dict]:
    """Two-layer grounding:
    1. evidence_span verbatim in full_text (LLM compliance — was the '100%' circular check)
    2. evidence_span actually SUPPORTS the atom (core value present in span — breaks circularity)

    grounded = layer1 AND layer2. This is deterministic, non-circular.
    """
    norm_full = _normws(full_text)
    out = []
    for a in atoms:
        if not isinstance(a, dict):
            continue
        a = dict(a)
        ev = a.get("evidence_span")
        norm_ev = _normws(ev)
        # Layer 1: span in text (LLM compliance)
        in_text = bool(norm_ev) and norm_ev in norm_full
        # Layer 2: span supports atom (non-circular, content-based)
        supported, support_reason = _supports(a, ev or "")
        a["grounded"] = in_text and supported
        a["grounded_span"] = ev if a["grounded"] else None
        a["in_text"] = in_text          # layer 1 (compliance)
        a["supported"] = supported       # layer 2 (non-circular)
        a["support_reason"] = support_reason
        out.append(a)
    return out


def attach_discourse_roles(atoms: list[dict], structure_map: dict) -> list[dict]:
    """Attach _discourse_role to each atom from its source node's section."""
    sections = structure_map.get("sections", [])
    dag = structure_map.get("dag", {"nodes": []})
    node_section = {str(n.get("id")): n.get("section") for n in dag.get("nodes", [])}
    sec_role = {s.get("name"): s.get("discourse_role") for s in sections}

    for a in atoms:
        if not isinstance(a, dict):
            continue
        nid = a.get("_source_node", "")
        sec = node_section.get(nid, "")
        a["_discourse_role"] = sec_role.get(sec, "unknown")
    return atoms


def find_rebind_candidates(atoms: list[dict]) -> list[dict]:
    """Deterministic rebind / misclassification detection.

    Detects two real signals (replaces the old surface+role check that found 0):
    (a) SAME surface form assigned DIFFERENT entity_types — a misclassification
        (e.g. "I_0" extracted as both MATERIAL_PARAMETER and DIMENSIONLESS_NUMBER).
        This is the actual type-confusion signal; role is irrelevant.
    (b) same surface form across definition vs non-definition discourse roles —
        a rebind candidate (original signal, kept but no longer the primary one).
    """
    groups: dict[str, list[dict]] = {}
    for a in atoms:
        if not isinstance(a, dict):
            continue
        if a.get("layer") != "L1":
            continue
        key = _normws(a.get("entity"))
        if not key:
            continue
        groups.setdefault(key, []).append(a)

    candidates = []
    seen = set()  # dedup by (atom id pair) to avoid double-flagging
    for key, group in groups.items():
        if len(group) < 2:
            continue
        types = {a.get("entity_type") for a in group}
        roles = {a.get("_discourse_role") for a in group}
        # (a) same surface, different types = misclassification (primary signal)
        if len(types) > 1:
            for a in group:
                aid = id(a)
                for b in group:
                    if id(b) <= aid:
                        continue
                    if a.get("entity_type") != b.get("entity_type"):
                        pair = tuple(sorted([str(aid), str(id(b))]))
                        if pair in seen:
                            continue
                        seen.add(pair)
                        candidates.append({
                            "atom": a,
                            "entity": a.get("entity"),
                            "types": sorted(types),
                            "roles": sorted(r for r in roles if r),
                            "reason": "same surface form assigned different entity_types (misclassification)",
                        })
                        break
        # (b) same surface across definition vs other role (original rebind signal)
        elif len(roles) > 1 and roles & DEFINITION_ROLES:
            for a in group:
                if a.get("_discourse_role") not in DEFINITION_ROLES:
                    candidates.append({
                        "atom": a,
                        "entity": a.get("entity"),
                        "types": sorted(types),
                        "roles": sorted(r for r in roles if r),
                        "reason": "entity surface defined in one section, reused in another",
                    })
    return candidates


def lookup(atoms: list[dict], structure_map: dict, blocks: list,
           llm: str = "deepseek") -> list[dict]:
    """One LLM call over all flagged atoms (ungrounded or low-confidence).

    Re-reads the relevant section text and asks the LLM to either confirm
    the evidence span (correcting it to a verbatim span) or mark the atom
    as unsupported. Returns the updated atoms list.
    """
    flagged = [a for a in atoms if isinstance(a, dict) and
               (not a.get("grounded") or float(a.get("confidence", 0) or 0) < 0.4)]
    if not flagged:
        return atoms

    # Collect section text needed for the flagged atoms.
    from granular_agent.structure_mapper import section_text_for_node
    sections = structure_map.get("sections", [])
    dag = structure_map.get("dag", {"nodes": []})
    node_map = {str(n.get("id")): n for n in dag.get("nodes", [])}

    needed_nodes = {}
    for a in flagged:
        nid = a.get("_source_node", "")
        if nid in node_map:
            needed_nodes.setdefault(nid, node_map[nid])

    sections_text = []
    for nid, node in needed_nodes.items():
        st = section_text_for_node(node, sections, blocks)
        sections_text.append(f"--- section: {node.get('section')} (node {nid}) ---\n{st}")
    combined_sections = "\n\n".join(sections_text)

    atom_briefs = []
    for i, a in enumerate(flagged):
        atom_briefs.append(f"[{i}] layer={a.get('layer')} type={a.get('type') or a.get('entity_type','')} "
                           f"value={a.get('entity') or a.get('statement') or a.get('relation','')} "
                           f"claimed_evidence={a.get('evidence_span','')}")
    briefs_text = "\n".join(atom_briefs)

    prompt = f"""You are re-checking atoms extracted from a granular flow paper. For each flagged atom below, search the section text and either:
1. Confirm the atom by providing a VERBATIM evidence span copied exactly from the section text (this will be exact-match checked), OR
2. Mark it "unsupported" if the section text does not actually support this atom.

Flagged atoms:
{briefs_text}

Section text:
{combined_sections}

Output a JSON array of objects, one per flagged atom in order, with shape:
{{"index": 0, "verdict": "confirmed"|"unsupported", "evidence_span": "<verbatim or empty>"}}

Output ONLY the JSON array."""

    raw = call_llm(prompt, model="deepseek-chat", max_tokens=4096) if llm == "deepseek" \
        else call_paratera(prompt, model=llm, max_tokens=4096)
    parsed = parse_json_response(raw)
    if not isinstance(parsed, list):
        return atoms

    norm_full = _normws(" ".join(b["text"] for b in blocks))
    by_index = {p.get("index"): p for p in parsed if isinstance(p, dict)}
    for i, a in enumerate(flagged):
        if not isinstance(a, dict):
            continue
        verdict = by_index.get(i, {})
        v = verdict.get("verdict")
        if v == "confirmed":
            ev = verdict.get("evidence_span", "")
            # Must re-pass BOTH layers: in_text AND _supports (no circular bypass)
            in_text = bool(ev) and _normws(ev) in norm_full
            supported, support_reason = _supports(a, ev)
            if in_text and supported:
                a["evidence_span"] = ev
                a["grounded"] = True
                a["grounded_span"] = ev
                a["in_text"] = True
                a["supported"] = True
                a["support_reason"] = support_reason
                a["confidence"] = max(float(a.get("confidence", 0) or 0), 0.6)
            else:
                a["grounded"] = False
                a["in_text"] = in_text
                a["supported"] = supported
                a["support_reason"] = f"lookup-fail: {support_reason}"
        elif v == "unsupported":
            a["_unsupported"] = True

    return atoms


def filter_grounded(atoms: list[dict]) -> list[dict]:
    """Keep only atoms that are grounded (or non-text atoms like PAPER/RQ that have no span requirement)."""
    out = []
    for a in atoms:
        if not isinstance(a, dict):
            continue
        layer = a.get("layer")
        # PAPER and RESEARCH_QUESTION atoms may legitimately lack a verbatim span; keep if statement exists.
        if layer in ("PAPER",) or (layer == "L3" and a.get("type") == "RESEARCH_QUESTION"):
            if a.get("_unsupported"):
                continue
            out.append(a)
            continue
        if a.get("_unsupported"):
            continue
        if a.get("grounded"):
            out.append(a)
    return out


def summary(atoms: list[dict]) -> dict:
    n = len(atoms)
    grounded = sum(1 for a in atoms if isinstance(a, dict) and a.get("grounded"))
    in_text = sum(1 for a in atoms if isinstance(a, dict) and a.get("in_text"))
    supported = sum(1 for a in atoms if isinstance(a, dict) and a.get("supported"))
    low_conf = sum(1 for a in atoms if isinstance(a, dict) and float(a.get("confidence", 0) or 0) < 0.4)
    return {"n_atoms": n, "n_grounded": grounded, "n_in_text": in_text,
            "n_supported": supported, "n_low_conf": low_conf,
            "grounded_rate": grounded / n if n else 0.0,
            "support_rate": supported / n if n else 0.0}
