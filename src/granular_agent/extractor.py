"""Extract capability: multi-LLM structured extraction per current schema version."""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.llm_client import call_llm, call_paratera, parse_json_response
from granular_agent.schema_manager import SchemaManager

MINERU_BASE = "C:/Users/D0n9/Desktop/science_evo/data/upstream/remote_mineru/mineru_2355/papers"

EXTRACT_PROMPT = """Extract structured information from this granular flow paper.

{schema_prompt}

CRITICAL: For L1 entity_type, you MUST use ONLY the entity types listed above. Do NOT invent new entity types like METHOD, MODEL, FLOW_TYPE, or PHYSICAL_ENTITY. If something is a method/algorithm, use DEVICE or MATERIAL_PARAMETER. If it's a physical object, use MATERIAL or SAMPLE.

Instructions:
- Extract atoms across L1 (entities), L2 (relations), L3 (contributions + relations + RQ).
- For each CONTRIBUTION, assign multi-label subtypes.
- For constitutive laws, also create a CLOSURE atom with input/output/function_form.
- Mark paper_type.
- Do NOT stuff experimental observations into constitutive_law. Use experimental_finding.
- Output ONLY a valid JSON array of atoms.

Atom formats:
L1: {{"layer":"L1","entity_type":"...","entity":"..."}}
L2: {{"layer":"L2","relation":"...","subject":"...","object":"...","conditions":[...]}}
L3 CONTRIBUTION: {{"layer":"L3","type":"CONTRIBUTION","statement":"...","subtypes":["..."],"params":[...]}}
L3 RELATION: {{"layer":"L3","type":"CONTRIBUTION_RELATION","relation":"...","from":"...","to":"...","qualifier":"..."}}
L3 RQ: {{"layer":"L3","type":"RESEARCH_QUESTION","statement":"..."}}
L3 CLOSURE: {{"layer":"L3","type":"CLOSURE","statement":"...","input_variables":[...],"output_variable":"...","function_form":"...","parameters":[...],"applicable_regime":"..."}}
PAPER: {{"layer":"PAPER","paper_type":"..."}}

PAPER TEXT:
{text}"""


def load_paper_text(paper_id: str, max_chars: int = 8000) -> str:
    """Load paper text from mineru content_list.json. Truncated to fit LLM context."""
    p = os.path.join(MINERU_BASE, paper_id, "content_list.json")
    if not os.path.isfile(p):
        return ""
    cl = json.load(open(p, encoding="utf-8"))
    # Take abstract + intro + method + results + conclusion (skip references/figures)
    texts = []
    for it in cl:
        if it.get("type") == "text" and it.get("text"):
            t = it["text"].strip()
            # Skip reference-like blocks
            if len(t) < 10 or t.startswith("[") and any(c.isdigit() for c in t[:5]):
                continue
            texts.append(t)
    full = " ".join(texts)
    # Truncate smartly: take beginning (abstract+intro) + end (conclusion)
    if len(full) > max_chars:
        half = max_chars // 2
        full = full[:half] + " ... [middle truncated] ... " + full[-half:]
    return full


def extract_single_llm(text: str, schema_prompt: str, llm: str = "deepseek") -> list[dict]:
    """Extract atoms using a single LLM."""
    prompt = EXTRACT_PROMPT.format(schema_prompt=schema_prompt, text=text)
    if llm == "deepseek":
        raw = call_llm(prompt, max_tokens=8192)
    else:
        raw = call_paratera(prompt, model=llm, max_tokens=8192)
    atoms = parse_json_response(raw)
    return atoms if isinstance(atoms, list) else []


def extract_multi_llm(text: str, schema_prompt: str, llms: list[str] = None) -> dict[str, list[dict]]:
    """Extract atoms using multiple LLMs in parallel."""
    if llms is None:
        llms = ["deepseek-chat"]  # Start with single LLM; add Kimi/Qwen later

    results = {}
    # Map model names
    llm_map = {
        "deepseek": ("deepseek", None),
        "kimi": (None, "Kimi-K2.6"),
        "qwen": (None, "Qwen3.5-27B"),
    }

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {}
        for llm_name in llms:
            ds_model, par_model = llm_map.get(llm_name, ("deepseek", None))
            if par_model:
                fut = pool.submit(extract_single_llm, text, schema_prompt, par_model)
            else:
                fut = pool.submit(extract_single_llm, text, schema_prompt, "deepseek")
            futs[fut] = llm_name

        for fut in as_completed(futs):
            name = futs[fut]
            try:
                results[name] = fut.result()
            except Exception:
                results[name] = []
    return results


def fuse_mary(multi_results: dict[str, list[dict]], embed_fn=None) -> list[dict]:
    """MARY fusion: union + semantic-neighborhood inclusion for minority atoms.

    For atoms that only one LLM extracted, check if they're semantically
    close to the majority set. If yes, include; if no, flag as candidate noise.
    """
    # Flatten all atoms
    all_atoms = []
    for atoms in multi_results.values():
        all_atoms.extend(atoms)

    if len(multi_results) <= 1:
        return all_atoms

    # Find majority (atoms in 2+ LLMs) and minority (only 1 LLM)
    # Use entity text as key for dedup
    atom_keys = {}
    for llm_name, atoms in multi_results.items():
        for atom in atoms:
            if not isinstance(atom, dict):
                continue
            # Create a key from the atom's content
            if atom.get("layer") == "L1":
                key = f"L1|{atom.get('entity_type', '')}|{atom.get('entity', '').lower()[:60]}"
            elif atom.get("layer") == "L3" and atom.get("type") == "CONTRIBUTION":
                key = f"L3C|{atom.get('statement', '').lower()[:80]}"
            else:
                continue  # Skip non-entity/contribution atoms for dedup

            if key not in atom_keys:
                atom_keys[key] = {"atom": atom, "llms": [llm_name], "count": 1}
            else:
                atom_keys[key]["llms"].append(llm_name)
                atom_keys[key]["count"] += 1

    # Build fused result
    fused = []
    majority_keys = set()
    minority_candidates = []

    for key, info in atom_keys.items():
        if info["count"] >= 2:
            fused.append(info["atom"])
            majority_keys.add(key)
        else:
            minority_candidates.append((key, info["atom"]))

    # For minority atoms, check semantic similarity to majority
    if embed_fn and minority_candidates and majority_keys:
        majority_texts = [atom_keys[k]["atom"].get("entity", "") or
                          atom_keys[k]["atom"].get("statement", "") for k in majority_keys]
        minority_texts = [a.get("entity", "") or a.get("statement", "") for _, a in minority_candidates]

        all_texts = minority_texts + majority_texts
        embeddings = embed_fn(all_texts)
        n_min = len(minority_texts)
        min_embs = embeddings[:n_min]
        maj_embs = embeddings[n_min:]

        from granular_agent.llm_client import cosine_sim
        for i, (key, atom) in enumerate(minority_candidates):
            # Check if this minority atom is semantically close to any majority atom
            max_sim = 0.0
            for maj_emb in maj_embs:
                sim = cosine_sim(min_embs[i], maj_emb)
                if sim > max_sim:
                    max_sim = sim
            if max_sim >= 0.5:  # MARY threshold
                fused.append(atom)
            # else: skip (candidate noise)
    else:
        # No embedding available, include all minority atoms (conservative)
        for _, atom in minority_candidates:
            fused.append(atom)

    # Add non-entity/contribution atoms (L2, L3 relations, PAPER, RQ, CLOSURE) from all LLMs
    seen_relations = set()
    for atoms in multi_results.values():
        for atom in atoms:
            if not isinstance(atom, dict):
                continue
            if atom.get("layer") in ("L2", "PAPER"):
                # Dedup L2 by subject+relation+object
                if atom.get("layer") == "L2":
                    rel_key = f"{atom.get('relation','')}|{atom.get('subject','')}|{atom.get('object','')}"
                    if rel_key in seen_relations:
                        continue
                    seen_relations.add(rel_key)
                fused.append(atom)
            elif atom.get("layer") == "L3" and atom.get("type") in ("CONTRIBUTION_RELATION", "RESEARCH_QUESTION", "CLOSURE"):
                fused.append(atom)

    return fused


class Extractor:
    """Extract capability: orchestrates multi-LLM extraction + MARY fusion."""

    def __init__(self, schema_manager: SchemaManager, llms: list[str] = None):
        self.schema_manager = schema_manager
        self.llms = llms or ["deepseek"]

    def extract(self, paper_id: str, use_fusion: bool = True) -> dict:
        """Extract atoms from a paper. Returns {paper_id, atoms, schema_version, gaps}."""
        text = load_paper_text(paper_id)
        if not text:
            return {"paper_id": paper_id, "atoms": [], "schema_version": self.schema_manager.current_version, "gaps": [], "error": "no_text"}

        schema_prompt = self.schema_manager.get_schema_prompt()

        if len(self.llms) == 1 or not use_fusion:
            # Single LLM extraction
            atoms = extract_single_llm(text, schema_prompt, self.llms[0] if self.llms[0] != "deepseek" else "deepseek")
        else:
            # Multi-LLM + fusion
            multi = extract_multi_llm(text, schema_prompt, self.llms)
            from granular_agent.llm_client import embed_batch
            atoms = fuse_mary(multi, lambda texts: embed_batch(texts) if texts else [])

        # Detect gaps (atoms that don't fit current schema)
        gaps = self._detect_gaps(atoms)

        return {
            "paper_id": paper_id,
            "atoms": atoms,
            "schema_version": self.schema_manager.current_version,
            "gaps": gaps,
            "n_atoms": len(atoms),
        }

    def _detect_gaps(self, atoms: list[dict]) -> list[dict]:
        """Detect atoms that don't fit the current schema (passive gap discovery)."""
        gaps = []
        valid_entity_types = set(t.upper() for t in self.schema_manager.get_entity_types())
        valid_subtypes = set(s.lower() for s in self.schema_manager.get_contribution_subtypes())
        valid_relations = set(r.lower() for r in self.schema_manager.get_relation_types())

        for atom in atoms:
            if not isinstance(atom, dict):
                continue
            if atom.get("layer") == "L1":
                et = atom.get("entity_type", "").upper()
                if et and et not in valid_entity_types:
                    gaps.append({
                        "type": "entity_type_not_in_schema",
                        "value": et,
                        "atom": atom,
                    })
            elif atom.get("layer") == "L3" and atom.get("type") == "CONTRIBUTION":
                for st in atom.get("subtypes", []):
                    if st.lower() not in valid_subtypes:
                        gaps.append({
                            "type": "contribution_subtype_not_in_schema",
                            "value": st,
                            "atom": atom,
                        })
            elif atom.get("layer") == "L3" and atom.get("type") == "CONTRIBUTION_RELATION":
                rel = atom.get("relation", "").lower()
                if rel and rel not in valid_relations:
                    gaps.append({
                        "type": "relation_type_not_in_schema",
                        "value": rel,
                        "atom": atom,
                    })

        return gaps
