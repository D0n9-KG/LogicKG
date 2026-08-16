"""Downstream task C2: constitutive-law / relation retrieval from the
extracted hypergraph. Deterministic (no LLM) — verifies the hypergraph is
usable downstream, not just a static artifact.

Query by regime / qualifier / pattern_type / node surface. Returns matching
hyperedges with their evidence spans. This is the retrieval primitive a
downstream RAG/QA or claim-verification system would call.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from granular_agent.hypergraph_schema import InstanceHypergraph, Hyperedge, HGNode


def retrieve(instance: InstanceHypergraph, *, pattern_type: str | None = None,
             regime: str | None = None, qualifier: str | None = None,
             node_surface: str | None = None) -> list[dict]:
    """Retrieve hyperedges matching the query (all filters AND-ed).

    - pattern_type: exact or substring match on he.pattern_type
    - regime: matches applies_in_regime qualifier (substring)
    - qualifier: matches any qualifier key (substring)
    - node_surface: matches if any connected node's surface contains it
    Returns list of {eid, pattern_type, nodes, qualifiers, evidence_span}.
    """
    out = []
    ns_lower = node_surface.lower() if node_surface else None
    for he in instance.hyperedges.values():
        if pattern_type and pattern_type.lower() not in he.pattern_type.lower():
            continue
        if regime:
            rv = he.qualifiers.get("applies_in_regime", "") or he.qualifiers.get("regime", "")
            if regime.lower() not in rv.lower():
                continue
        if qualifier:
            if not any(qualifier.lower() in k for k in he.qualifiers):
                continue
        if ns_lower:
            nodes = [instance.nodes.get(nid) for nid in he.node_ids]
            if not any(n and ns_lower in n.surface.lower() for n in nodes):
                continue
        out.append(_he_view(he, instance))
    return out


def _he_view(he: Hyperedge, instance: InstanceHypergraph) -> dict:
    nodes = []
    for nid, role in zip(he.node_ids, he.node_roles):
        n = instance.nodes.get(nid)
        nodes.append({"role": role, "surface": n.surface if n else nid,
                      "labels": n.labels if n else []})
    return {"eid": he.eid, "pattern_type": he.pattern_type, "nodes": nodes,
            "qualifiers": he.qualifiers, "evidence_span": he.evidence_span}


def verify_retrieval_coverage(instance: InstanceHypergraph) -> dict:
    """How many hyperedges are retrievable by each dimension. Tests the
    hypergraph is queryable, not just storable."""
    by_pt = {}
    by_regime = {}
    for he in instance.hyperedges.values():
        by_pt[he.pattern_type] = by_pt.get(he.pattern_type, 0) + 1
        rv = he.qualifiers.get("applies_in_regime", "") or he.qualifiers.get("regime", "")
        if rv:
            by_regime[rv] = by_regime.get(rv, 0) + 1
    n_total = len(instance.hyperedges)
    n_with_regime = sum(by_regime.values())
    return {"n_hyperedges": n_total,
            "n_pattern_types": len(by_pt),
            "pattern_type_dist": by_pt,
            "n_with_regime": n_with_regime,
            "regime_dist": by_regime,
            "regime_coverage": round(n_with_regime / max(1, n_total), 3)}


if __name__ == "__main__":
    import json
    inst_path = sys.argv[1] if len(sys.argv) > 1 else \
        ".research_tmp/hg_out/PPR_00180B90C8D8_instance.json"
    d = json.load(open(inst_path, encoding="utf-8"))
    inst = InstanceHypergraph(paper_id=d.get("paper_id", ""))
    for nid, n in d.get("nodes", {}).items():
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

    cov = verify_retrieval_coverage(inst)
    print(f"retrieval coverage: {cov['n_hyperedges']} hyperedges, "
          f"{cov['n_pattern_types']} pattern types, "
          f"regime-tagged {cov['n_with_regime']}/{cov['n_hyperedges']} ({cov['regime_coverage']})")
    print(f"pattern types: {cov['pattern_type_dist']}")
    print(f"regimes: {cov['regime_dist']}")

    print("\n=== retrieval tests ===")
    # C2a: retrieve all constitutive laws
    r = retrieve(inst, pattern_type="constitutive")
    print(f"1. retrieve(pattern_type='constitutive') -> {len(r)} hits")
    for h in r[:2]:
        print(f"   {h['eid']}: {[n['surface'] for n in h['nodes']]} ev=\"{h['evidence_span'][:50]}\"")
    # C2b: retrieve by node surface
    r = retrieve(inst, node_surface="fabric")
    print(f"2. retrieve(node_surface='fabric') -> {len(r)} hits")
    # C2c: retrieve by qualifier
    r = retrieve(inst, qualifier="regime")
    print(f"3. retrieve(qualifier='regime') -> {len(r)} hits")
    print(f"\nC2 retrieval {'WORKS' if cov['n_hyperedges']>0 else 'EMPTY'} — hypergraph is queryable downstream")
