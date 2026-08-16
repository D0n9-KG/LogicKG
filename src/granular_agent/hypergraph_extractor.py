"""Phase 1 (hypergraph): chained extraction producing hyperedges, with the
deep self-evolution closed loop wired in.

Mirrors chained_extractor.py's DAG/blackboard topology but emits hyperedges
(not flat atoms). Each extracted hyperedge is validated against the
meta-hypergraph; structural mismatches feed
hypergraph_evolution.run_evolution_loop, which mutates the meta-hypergraph
in place. Downstream DAG nodes then re-fetch meta.to_prompt() — this is
P4 forward propagation (the schema a later node sees reflects evolution
that happened at an earlier node).

This is the ENTRY of the closed loop: without real hyperedges there is
nothing to validate, so the trigger never fires.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.llm_client import call_llm, call_paratera, parse_json_response
from granular_agent.structure_mapper import topo_order, section_text_for_node
from granular_agent.hypergraph_schema import (
    MetaHypergraph, Hyperedge, HGNode, InstanceHypergraph,
)
from granular_agent.hypergraph_evolution import EvolutionTrigger, run_evolution_loop

SECTION_TEXT_CAP = None  # no truncation — DAG splits full text into sections;
# each node handles its own section's COMPLETE text (the core DAG卖点, see
# structure_mapper). An 8000-char cap here previously re-broke full-text
# coverage on long Method/Results sections — removed.


def _norm_surface(s: str) -> str:
    """Normalize a node surface for cross-section dedup: NFKC, lowercase,
    collapse whitespace/punctuation. "Granular Materials" == "granular
    materials" == "granular  materials"."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s.lower())
    s = re.sub(r"[\s\-_]+", " ", s).strip(" .,;:()")
    return s


EXTRACT_HG_PROMPT = """You are extracting a knowledge HYPERGRAPH from ONE section of a {domain} paper.

{schema_prompt}

This section's discourse role is: {discourse_role}.

Extract:
1. NODES: the physical entities/quantities/values mentioned in this section. Each node has >=1 label from the schema's node types above, a surface (the mention text), and a verbatim evidence_span copied exactly from the section.
2. HYPEREDGES: the N-ARY relations connecting those nodes. A hyperedge connects N nodes (N>=2, and N>=3 whenever the relation is genuinely n-ary — see below). Each hyperedge has a pattern_type, node_ids (the nodes it connects, in order), node_roles, qualifiers, and a verbatim evidence_span.

Rules:
- node_roles = the FUNCTIONAL ROLE of each node IN the relation, NOT the node's name/entity. A role describes the node's position in this relation. Use ONLY these role kinds (pick the best fit; pluralize/repeat for multiple same-role nodes):
    * output / input — for laws/dependencies (what's computed vs what feeds it)
    * cause / effect — for causal relations
    * subject / object — for general relations
    * from / to — for directional/claim relations
    * whole / component — for compositional/part-of relations
    * source / target — for influence/flow relations
    * instrument / object — for measurement (what measures vs what's measured)
    * exponent / parameter / coefficient — for numeric roles in equations
  Do NOT use entity names or property names as roles. "shear_rate", "stress", "velocity", "volume_fraction" are NODES (surfaces), NOT roles — the role of shear_rate in "stress depends on shear_rate" is "input", NOT "shear_rate". Using an entity name as a role is a category error and breaks schema reuse.
  Keep roles from this small set; reuse the SAME role name across hyperedges of the same pattern (e.g. all constitutive_law edges use output/input, not some using "stress_role" and others "dependent"). This lets the schema recognize the same relation structure across papers.
- evidence_span MUST be a verbatim phrase copied from the section (exact string, including symbols/units). Paraphrasing causes rejection.
- Use existing patterns when they fit. Only propose a NEW pattern_type when the section expresses a relation none of the existing patterns can hold (the system will validate it).
- A node can carry multiple labels (e.g. a dimensionless number is both NUMERIC and a dimensionless quantity).
- HYPERGRAPH = N-ARY (the core point, do NOT degrade to binary):
    * A constitutive_law / governing equation MUST be ONE hyperedge connecting its output PLUS every input it depends on PLUS every named constant/parameter. E.g. "stresses are proportional to the square of the shear rate" -> ONE arity-3 edge: [stress(output) <- shear_rate(input) <- 2(exponent)] — NOT two binary edges. "increase with both particle diameter and curvature of the shear surfaces" -> ONE arity-3 edge [stress <- particle_diameter <- curvature].
    * If a relation has 1 output and >=2 inputs, the hyperedge MUST connect all of them (arity = 1 + n_inputs + n_params).
    * Only use arity 2 for genuinely binary relations (A depends on B alone, nothing else).
- COORDINATED ENTITIES MUST SHARE ONE EDGE (the most common arity-loss bug): when
  a sentence lists PARALLEL entities all in the same relation to the same
  other entity, they MUST all be nodes of ONE hyperedge, NOT split into
  separate binary edges and NOT dropped. Examples:
    "strain hardening, strength anisotropy and deformational anisotropy had a
     strong dependence on the distribution of contact normals" ->
       ONE arity-4 edge [strain_hardening, strength_anisotropy, deformational_anisotropy] <- distribution_of_contact_normals
       (three dependents, one independent — arity 4, dependency_type=monotonic).
    "the stresses increase with both particle diameter and curvature" ->
       ONE arity-3 edge stress <- [particle_diameter, curvature] (arity 3).
  Do NOT extract only the first listed entity and drop the rest — that loses
  information and orphans the dropped nodes. If the schema's pattern has a
  repeatable input/dependent role, use it; if not, propose a new pattern that
  does (the system will validate variadic patterns).
- NUMERIC NODES (REQUIRED): every number, constant, coefficient, exponent, and measured value in the section MUST be emitted as a NUMERIC node (with properties.value set). Constitutive-law parameters (mu_s, friction coefficient, exponents, critical values) MUST be nodes AND wired into the constitutive_law hyperedge. A physics section with zero NUMERIC nodes is WRONG.
- NO ORPHAN NODES: every node you emit MUST participate in >=1 hyperedge. If you would emit a node that no edge connects, either (a) find the edge it belongs to and add it, or (b) do NOT emit that node. Dangling mentions are noise.
- NO DUPLICATE NODES: before emitting a node, check if an existing node has the SAME surface (case/punctuation-insensitive). If so, reuse its nid; do NOT create a second node for "Granular Materials" when "granular materials" exists.
- Equations/laws: when the section states a quantitative law (output computed from inputs + parameters), emit ONE n-ary hyperedge wiring the output + every input + every named constant/parameter as nodes. Carry the equation text in a qualifier if a function-form key is among the pattern's allowed_qualifiers. Pick the pattern_type from the schema's existing patterns (shown above); if the schema lacks a fitting pattern, use the relation's natural name as pattern_type (the system will validate + evolve the schema to accommodate it).
- Be exhaustive but wired: extract every distinct entity and relation, and ensure every node is connected. A section typically yields 8-20 nodes and 5-12 hyperedges, with most hyperedges arity>=3.
- node_ids must reference node nid values you defined in THIS output.
- CONTROLLED-ENUM relation kind (REQUIRED for any dependency/relates pattern): the
  `dependency_type` (or `relation_kind`) qualifier MUST take one of these enum
  values, picked by the SEMANTICS of the relation (not the surface verb):
    * "monotonic"   — one quantity varies monotonically with another (increases/decreases with, scales as, ratio)
    * "derivation"  — one relation is derived/follows/depends on another (derived from, follows from, depends on)
    * "analogy"     — one relation is proposed as analogous/representative of another (possible representation, corresponds to)
    * "composition" — one relation is composed of / accounts for / is a measure of another (divided by, accounts for, is a measure of)
  Do NOT write free-text values like "increases with" or "possible representation" — write the enum value. This constraint is what lets the schema-refinement loop detect over-wide patterns and split them.
- applies_in_regime (when the pattern declares it as an allowed qualifier):
  carry it as a SHORT tag chosen from: dense, quasi-static, inertial, solid-like, flow, static, unknown. If the section does not specify a regime, use "unknown".
- cited_from provenance (REQUIRED): every hyperedge carries cited_from, one of:
    * "this_work"   — the relation is asserted by THIS paper's own experiments/analysis
    * "prior_art"   — the relation is reported as another's result being cited/built on (the evidence span will name the cited work or use citation markers)
    * "definition"  — the relation is a definitional identity (e.g. "X is defined as Y")
  This distinguishes the paper's own claims from work it cites (a missing
  provenance qualifier causes silent mis-attribution).
- method (REQUIRED when the source specifies it): how the relation was established, one of:
    * "experiment"  — measured in an experiment / apparatus
    * "simulation"  — from a numerical simulation (DEM/CFD/etc)
    * "theory"      — derived theoretically / analytically
    * "review"      — surveyed / asserted in a review without derivation
  Pick by how THIS paper establishes the relation, not by the field. Omit only if the section genuinely does not say.
- evidence_strength (REQUIRED): the epistemic status of the relation, one of:
    * "measured"     — directly measured / observed
    * "derived"      — derived from other quantities / computed
    * "hypothesized"  — proposed as a hypothesis / assumption
    * "assumed"       — taken as a modeling assumption
  This + cited_from + method together give the hyper-relational provenance (P-E2 attribution).
- qualifier keys are FIXED: only use keys from {{condition, method, evidence_strength,
  cited_from, applies_in_regime, dependency_type, relation_type, function_form,
  parameters}}. An ad-hoc key is rejected. Do not invent qualifier names. For enum
  keys (method/evidence_strength/dependency_type/applies_in_regime/cited_from) the
  VALUE must be exactly one of the enum values listed above — free-text values like
  "seminar discussion" or "qualitative" are rejected.

{predecessor_context}

SECTION TEXT ({section_name}):
{section_text}

Output a JSON object (note: hyperedges are N-ARY — connect >=3 nodes when the relation involves multiple inputs/dependents):
{{"nodes":[{{"nid":"n1","labels":["PROPERTY"],"surface":"stress","evidence_span":"stresses tend to be proportional to the square of the shear rate","properties":{{}}}},
          {{"nid":"n2","labels":["PROPERTY"],"surface":"shear rate","evidence_span":"...","properties":{{}}}},
          {{"nid":"n3","labels":["NUMERIC","PROPERTY"],"surface":"2","evidence_span":"...","properties":{{"value":2}}}}],"hyperedges":[{{"eid":"e1","pattern_type":"constitutive_law","node_ids":["n1","n2","n3"],"node_roles":["output","input","input"],"qualifiers":{{"applies_in_regime":"flow","function_form":"stress ~ (shear rate)^2","parameters":["2"],"cited_from":"this_work"}},"evidence_span":"stresses tend to be proportional to the square of the shear rate"}}],"summary":"<=150 token compact summary for the next section"}}
Output ONLY the JSON object."""


class HGBlackboard:
    """JSON carrier: per-node summaries for chained context."""

    def __init__(self):
        self.summaries: dict[str, str] = {}

    def add(self, node_id: str, summary: str):
        self.summaries[node_id] = summary

    def predecessor_summary(self, deps: list[str]) -> str:
        if not deps:
            return ""
        parts = [f"[{d}] {self.summaries[d]}" for d in deps if d in self.summaries]
        return "Predecessor extracts:\n" + "\n".join(parts) if parts else ""


def _call(prompt: str, llm: str, max_tokens: int = 8192) -> str | None:
    if llm == "deepseek":
        return call_llm(prompt, model="deepseek-chat", max_tokens=max_tokens)
    return call_paratera(prompt, model=llm, max_tokens=max_tokens)


def _parse_hg_response(raw: str | None, node_id: str) -> tuple[list[HGNode], list[Hyperedge], str]:
    """Parse LLM output into HGNode/Hyperedge. Rewrites nids with a node_id
    prefix so nodes from different DAG nodes never collide."""
    if not raw:
        return [], [], ""
    parsed = parse_json_response(raw)
    if not isinstance(parsed, dict):
        return [], [], ""
    raw_nodes = parsed.get("nodes", []) or []
    raw_hes = parsed.get("hyperedges", []) or []
    summary = parsed.get("summary", "") or ""

    # nid remap: LLM-local nid -> global nid
    remap: dict[str, str] = {}
    nodes: list[HGNode] = []
    for n in raw_nodes:
        if not isinstance(n, dict):
            continue
        local = str(n.get("nid", ""))
        if not local:
            continue
        gid = f"{node_id}_{local}"
        remap[local] = gid
        labels = n.get("labels", []) or []
        if isinstance(labels, str):
            labels = [labels]
        nodes.append(HGNode(
            nid=gid, labels=[str(l) for l in labels if l],
            surface=str(n.get("surface", "")),
            properties=n.get("properties", {}) if isinstance(n.get("properties"), dict) else {},
            evidence_span=str(n.get("evidence_span", "")),
        ))
    hes: list[Hyperedge] = []
    for i, h in enumerate(raw_hes):
        if not isinstance(h, dict):
            continue
        local_ids = h.get("node_ids", []) or []
        gids = [remap.get(str(x), str(x)) for x in local_ids]  # remap if known
        roles = [str(r) for r in (h.get("node_roles", []) or [])]
        quals = h.get("qualifiers", {}) if isinstance(h.get("qualifiers"), dict) else {}
        quals = {str(k): str(v) for k, v in quals.items()}
        hes.append(Hyperedge(
            eid=f"{node_id}_e{i}", pattern_type=str(h.get("pattern_type", "")),
            node_ids=gids, node_roles=roles, qualifiers=quals,
            evidence_span=str(h.get("evidence_span", "")),
        ))
    return nodes, hes, summary


CHUNK_THRESH = 6000  # over-long sections (>6k chars) drown one LLM call —
                     # Discussion/Results can be 23k chars -> 0 edges. Chunk on
                     # sentence boundaries into ~6k pieces, multiple calls,
                     # merge. (the cross-chunk surface dedup handles node reuse.)


def _chunk_text(text: str, thresh: int = CHUNK_THRESH) -> list[str]:
    """Split over-long section text into ~thresh-char chunks on sentence
    boundaries. Returns [text] if short enough."""
    if len(text) <= thresh:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + thresh, len(text))
        if end < len(text):
            # extend to next sentence end to avoid mid-sentence cuts
            for sep in (". ", "? ", "! "):
                pos = text.rfind(sep, start + thresh // 2, end + thresh)
                if pos > 0:
                    end = pos + 1
                    break
            else:
                end = min(end + 200, len(text))
        chunks.append(text[start:end])
        start = end
    return [c for c in chunks if c.strip()]


def _run_hg_node(node: dict, sections: list, blocks: list, schema_prompt: str,
                 bb: HGBlackboard, llm: str, domain: str) -> tuple[list[HGNode], list[Hyperedge], str]:
    sec_text = section_text_for_node(node, sections, blocks)
    if not sec_text:
        return [], [], ""
    discourse_role = _discourse_for_node(node, sections)
    predecessor = bb.predecessor_summary(node.get("deps", []))
    chunks = _chunk_text(sec_text)
    all_nodes: list[HGNode] = []
    all_edges: list[Hyperedge] = []
    summary = ""
    for ci, chunk in enumerate(chunks):
        nid_prefix = f"{node['id']}c{ci}" if len(chunks) > 1 else node["id"]
        prompt = EXTRACT_HG_PROMPT.format(
            domain=domain, schema_prompt=schema_prompt,
            discourse_role=discourse_role, predecessor_context=predecessor,
            section_name=node.get("section", ""), section_text=chunk,
        )
        raw = _call(prompt, llm)
        cnodes, cedges, csum = _parse_hg_response(raw, nid_prefix)
        all_nodes.extend(cnodes)
        all_edges.extend(cedges)
        if not summary and csum:
            summary = csum
        elif csum:
            summary = (summary + " " + csum)[:600]
    return all_nodes, all_edges, summary


def _discourse_for_node(node: dict, sections: list) -> str:
    sec = next((s for s in sections if s.get("name") == node.get("section")), None)
    return sec.get("discourse_role", "unknown") if sec else "unknown"


_ORG_HINTS = ("university", "department", "institute", "faculty", "laboratory",
              "college", "school of", "center for", "division of")


def _extract_metadata(blocks: list, paper_id: str) -> dict:
    """Heuristically pull paper-level metadata from the leading mineru blocks:
    the first text block is usually the title; subsequent text blocks (until
    an org affiliation / abstract / section heading) are author names.
    doi/year/venue are left empty here — they need upstream lookup and are
    filled by the caller when available. This gives every extracted graph a
    minimal provenance header so downstream can map hyperedge -> paper without
    a separate join."""
    md = {"paper_id": paper_id, "title": "", "authors": [],
          "doi": "", "year": "", "venue": ""}
    texts = [b.get("text", "").strip() for b in blocks
             if b.get("type", "") in ("", "text") and b.get("text", "").strip()]
    if not texts:
        return md
    md["title"] = texts[0][:300]
    # scan the leading ~8 blocks for doi/year/venue — many mineru extractions
    # carry a citation line like "Citation: J. Rheol. 23, 243 (1979); doi: 10.xxx"
    import re as _re
    lead = " ".join(texts[:8])
    doi_m = _re.search(r"10\.\d{4,9}/[^\s\"';]+", lead)
    if doi_m:
        md["doi"] = doi_m.group(0).rstrip(".,);")
    year_m = _re.search(r"\b(1[89]\d{2}|20[0-3]\d)\b", lead)
    if year_m:
        md["year"] = year_m.group(0)
    # venue: text before the year in a "Citation:" line, e.g. "J. Rheol. 23, 243"
    cit_m = _re.search(r"(?:Citation|Published in)[:\s]+([^.]*?)\d{1,3}\s*,?\s*\d+", lead)
    if cit_m:
        md["venue"] = cit_m.group(1).strip(" ,;")[:120]
    authors = []
    for t in texts[1:6]:
        tl = t.lower()
        if any(h in tl for h in _ORG_HINTS) or len(t) > 120 or "abstract" in tl:
            break
        if "doi" in tl or "citation" in tl or "view online" in tl or "http" in tl:
            break  # citation/metadata line, not an author
        if "." in t and len(t.split()) > 8:
            break
        authors.append(t[:120])
    md["authors"] = authors[:8]
    # if doi still missing, look it up by title via Crossref (no key needed).
    # Cached per paper_id so re-extraction doesn't re-hit the network. Falls
    # back silently to the heuristic values on any failure. We cross-check
    # the year: if Crossref's top hit year != the heuristic year, the title
    # query likely matched a same-named different paper -> drop the crossref
    # doi (keep heuristic year which came from the paper's own "Dated:" line).
    if not md["doi"] and md["title"]:
        cr = _crossref_lookup(md["title"], paper_id)
        if cr:
            cr_year = str(cr.get("year", "") or "")
            if md["year"] and cr_year and md["year"] != cr_year:
                pass  # year mismatch -> likely wrong match, skip crossref doi
            else:
                md["doi"] = md["doi"] or cr.get("doi", "")
                md["venue"] = md["venue"] or cr.get("venue", "")
                md["lookup_source"] = "crossref"
    return md


_CROSSREF_CACHE: dict[str, dict] = {}


def _crossref_lookup(title: str, paper_id: str) -> dict | None:
    """Query Crossref by title to fill doi/year/venue. Cached per paper_id.
    No API key needed (polite pool). Returns None on any failure."""
    if paper_id in _CROSSREF_CACHE:
        return _CROSSREF_CACHE[paper_id] or None
    import urllib.request, urllib.parse
    try:
        q = urllib.parse.quote(title[:200])
        url = (f"https://api.crossref.org/works?query.title={q}&rows=1"
               f"&select=DOI,title,issued,container-title")
        req = urllib.request.Request(url, headers={"User-Agent": "LogicKG/0.1 (mailto:noreply)"})
        raw = urllib.request.urlopen(req, timeout=12).read()
        items = json.loads(raw).get("message", {}).get("items", [])
        if not items:
            _CROSSREF_CACHE[paper_id] = {}; return None
        it = items[0]
        yr = it.get("issued", {}).get("date-parts", [[None]])
        yr = yr[0][0] if yr and yr[0] else None
        res = {"doi": it.get("DOI", ""),
               "title_match": (it.get("title") or [""])[0],
               "year": yr, "venue": (it.get("container-title") or [""])[0][:120]}
        _CROSSREF_CACHE[paper_id] = res
        return res
    except Exception:
        _CROSSREF_CACHE[paper_id] = {}
        return None


def extract_hypergraph(structure_map: dict, blocks: list, meta: MetaHypergraph,
                       llm: str = "deepseek", paper_id: str = "",
                       domain: str = "granular flow physics",
                       trigger: EvolutionTrigger | None = None) -> dict:
    """Phase 1: run all DAG nodes in topo order, producing an InstanceHypergraph
    and evolving the meta-hypergraph in place (deep self-evolution closed loop).

    `meta` is mutated in place (caller holds the shared schema for cross-paper
    evolution). `trigger` may be passed in to persist cross-paper recurrence
    accounting; a fresh one is created if None.

    Returns {instance, evolutions, n_calls, n_nodes, n_hyperedges, validation_failures}.
    """
    sections = structure_map.get("sections", [])
    dag = structure_map.get("dag", {"nodes": []})
    nodes = topo_order(dag)

    instance = InstanceHypergraph(paper_id=paper_id)
    instance.metadata = _extract_metadata(blocks, paper_id)
    trigger = trigger or EvolutionTrigger()
    bb = HGBlackboard()
    n_calls = 0
    all_evolutions: list[dict] = []
    total_failures = 0
    failed_edges: list[dict] = []  # debug: rejected edges + reasons
    surface2nid: dict[str, str] = {}  # cross-section surface dedup

    for node in nodes:
        # P4 forward propagation: re-fetch the (possibly evolved) schema prompt
        schema_prompt = meta.to_prompt()
        hg_nodes, hg_edges, summary = _run_hg_node(node, sections, blocks, schema_prompt, bb, llm, domain)
        n_calls += 1

        # add nodes to the instance graph (dedup by SURFACE, cross-section):
        # the LLM re-extracts "granular materials"/"fabric" in each section
        # with fresh nids. Merge by normalized surface: reuse the existing
        # nid, union labels, keep first evidence. Remap this batch's edges.
        local_remap: dict[str, str] = {}
        for n in hg_nodes:
            key = _norm_surface(n.surface)
            if key and key in surface2nid:
                existing = instance.nodes.get(surface2nid[key])
                if existing:
                    for l in n.labels:
                        if l not in existing.labels:
                            existing.labels.append(l)
                    local_remap[n.nid] = existing.nid
                    continue
            if n.nid not in instance.nodes:
                instance.add_node(n)
                if key:
                    surface2nid[key] = n.nid
            local_remap[n.nid] = n.nid
        # remap edge node_ids to dedup'd nids
        for he in hg_edges:
            he.node_ids = [local_remap.get(nid, nid) for nid in he.node_ids]

        # validate each hyperedge; collect structural failures
        failures: list[tuple[Hyperedge, str]] = []
        for he in hg_edges:
            # only validate edges whose nodes all exist in the instance
            if not all(nid in instance.nodes for nid in he.node_ids):
                continue
            ok, reason = meta.validate(he, instance)
            if not ok:
                failures.append((he, reason))
                failed_edges.append({"node": node["id"], "pattern_type": he.pattern_type,
                    "arity": len(he.node_ids), "roles": he.node_roles,
                    "qualifier_keys": list(he.qualifiers.keys()), "reason": reason,
                    "evidence": he.evidence_span[:80]})
            else:
                instance.add_hyperedge(he)
        total_failures += len(failures)

        # closed loop: failures -> probe -> validate -> apply (mutates meta in place)
        if failures:
            evols, nc = run_evolution_loop(meta, failures, trigger, node["id"], paper_id,
                                           domain=domain, llm=llm, instance=instance)
            n_calls += nc
            all_evolutions.extend(evols)
            # After evolution, re-validate the failed edges that were held out:
            # an accepted new pattern/type may now accommodate them.
            for he, _ in failures:
                ok2, _ = meta.validate(he, instance)
                if ok2:
                    instance.add_hyperedge(he)

        bb.add(node["id"], summary)

    return {
        "instance": instance,
        "evolutions": all_evolutions,
        "n_calls": n_calls,
        "n_nodes": len(instance.nodes),
        "n_hyperedges": len(instance.hyperedges),
        "validation_failures": total_failures,
        "failed_edges": failed_edges,
    }
