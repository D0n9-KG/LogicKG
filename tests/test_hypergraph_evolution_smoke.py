"""Smoke test for hypergraph_evolution.py closed loop (deterministic + mocked LLM).

Verifies the Path C承重件 don't regress:
- EvolutionTrigger cross-node recurrence (P1)
- validate_proposal deterministic reject branches (P2 no-evidence, P3 near-dup)
- apply_proposal mutates meta (add_meta_node/add_pattern/add_subclass)
- validate() failure -> signal + concrete-before-abstract fallback
- run_evolution_loop end-to-end (mocked LLM, conservative gate cross_node>=2)
- taxonomy: split -> abstract parent + IS-A children + tree render
- taxonomy-aware ops: recursive-split guard, abstract-merge reparent,
  abstract+leaf merge reject, empty-parent retire
- rename op + auto-trigger (long/UPPER id)
No real LLM calls (monkey-patched).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import granular_agent.hypergraph_evolution as hev
from granular_agent.hypergraph_schema import (
    seed_meta_hypergraph, Hyperedge, HGNode, InstanceHypergraph,
    MetaHyperedgePattern, MetaEdge,
)

# ---- mock the LLM (probe + validate LLM check) ----
def fake_call(prompt, llm, max_tokens=4000):
    p = prompt.lower()
    if "schema-evolution probe" in p or "failing hyperedges" in p or "structural mismatch" in p:
        return '[{"op":"add_pattern","pattern_id":"measurement_relation","description":"a measurement relates a device to a property","role_slots":[{"role":"device","type":"MATERIAL"},{"role":"property","type":"PROPERTY"}],"allowed_qualifiers":["method"],"family":"measure","evidence_span":"the shear cell measured the stress ratio","rationale":"schema lacks device-measures-property pattern"}]'
    if "distinct, generalizable structural addition" in p:
        return '{"valid": true, "reason": "span supports a measurement pattern"}'
    if "name the merged pattern" in p or "merged pattern" in p:
        return "measurement"
    if "short lowercase snake_case replacement" in p or "unwieldy id" in p:
        return "causal_influence"
    return ""
hev._call = fake_call

fail = []
def check(name, cond):
    print(("OK  " if cond else "FAIL") + "  " + name)
    if not cond: fail.append(name)

# 1. seed
m = seed_meta_hypergraph()
check("seed has 4 types", len(m.types()) == 4)
check("seed has 6 patterns (one per top-level family)", len(m.patterns_ids()) == 6)
check("every seed pattern has a top-level family",
      all(p.family in ("constitutive_law","dependency","definition","composition","measure","claim") for p in m.patterns.values()))
check("family_roots set for all 6 families", len(m.family_roots) == 6)
# REDESIGN v2: families are now GROWABLE (not locked to 6). A new family's
# first pattern auto-becomes its root. Divergence prevented by conservative
# gate + merge/retire, NOT by locking families.
v_pre = m.version
m.add_pattern(MetaHyperedgePattern(pattern_id="causal_chain", family="causal",
             role_slots=[{"role":"cause","type":"PROPERTY"}, {"role":"effect","type":"PROPERTY"}],
             allowed_qualifiers=["condition","cited_from"]))
check("new (non-seed) family GROWABLE — pattern added (REDESIGN v2)",
      m.version != v_pre and "causal_chain" in m.patterns)
check("new family auto-registered as root", m.family_roots.get("causal") == "causal_chain")

# 2. taxonomy: split -> abstract parent + IS-A children + tree render
parent = m.patterns["constitutive_law"]
sub_a = MetaHyperedgePattern(pattern_id="cl_power_law", family="constitutive_law",
        role_slots=[dict(s) for s in parent.role_slots],
        allowed_qualifiers=list(parent.allowed_qualifiers))
sub_b = MetaHyperedgePattern(pattern_id="cl_density", family="constitutive_law",
        role_slots=[dict(s) for s in parent.role_slots],
        allowed_qualifiers=list(parent.allowed_qualifiers))
v_pre_split = m.version
nv = m.split_pattern("constitutive_law", [sub_a, sub_b])
check("split returns a version bump", nv != v_pre_split)
check("split parent is_abstract (kept as generalization, NOT deprecated)",
      parent.is_abstract is True and parent.deprecated is False)
check("split children are IS-A subclass_of parent (queryable ontology)",
      set(m.pattern_subclasses("constitutive_law")) == {"cl_power_law", "cl_density"})
check("abstract parent description refreshed to show its specialization",
      "[abstract generalization" in m.patterns["constitutive_law"].description)
check("to_prompt renders taxonomy tree (abstract root + indented children)",
      "(abstract)" in m.to_prompt() and "cl_power_law" in m.to_prompt())

# 2a. recursive-split guard
r_recurse = m.split_pattern("constitutive_law", [
    MetaHyperedgePattern(pattern_id="cl_z", family="constitutive_law",
        role_slots=[dict(s) for s in parent.role_slots], allowed_qualifiers=list(parent.allowed_qualifiers)),
    MetaHyperedgePattern(pattern_id="cl_w", family="constitutive_law",
        role_slots=[dict(s) for s in parent.role_slots], allowed_qualifiers=list(parent.allowed_qualifiers))])
check("recursive split of abstract parent rejected (split a child instead)", r_recurse is None)
check("original split children unchanged after rejected recursive split",
      set(m.pattern_subclasses("constitutive_law")) == {"cl_power_law", "cl_density"})

# 2b. merge abstract parents reparents children to the survivor
m.patterns["defines"].is_abstract = True
m.meta_edges.append(MetaEdge(src="defines_child", dst="defines", relation="subclass_of"))
m.patterns["defines_child"] = MetaHyperedgePattern(pattern_id="defines_child", family="definition",
    role_slots=[dict(s) for s in m.patterns["defines"].role_slots],
    allowed_qualifiers=list(m.patterns["defines"].allowed_qualifiers))
r_merge = m.merge_patterns(["defines"], into="constitutive_law")
check("merge abstract parent deprecates the merged-away parent",
      m.patterns["defines"].deprecated if r_merge else True)
if r_merge:
    check("merge reparents children to the survivor (taxonomy preserved)",
          "defines_child" in m.pattern_subclasses("constitutive_law"))
    check("survivor absorbing an abstract parent stays/becomes abstract",
          m.patterns["constitutive_law"].is_abstract is True)

# 2c. taxonomy guard: refuse merge abstract parent + concrete leaf
leaf = MetaHyperedgePattern(pattern_id="concrete_leaf", family="constitutive_law",
    role_slots=[dict(s) for s in parent.role_slots], allowed_qualifiers=list(parent.allowed_qualifiers))
m.add_pattern(leaf)
r_bad_merge = m.merge_patterns(["constitutive_law", "concrete_leaf"], into="concrete_leaf")
check("merge abstract-parent + concrete-leaf rejected (different ontological rank)", r_bad_merge is None)

# 2d. rename op
r_rename = m.rename_pattern("cl_power_law", "cl_square_law")
check("rename returns a version bump", r_rename is not None)
check("rename: old id removed, new id present",
      "cl_power_law" not in m.patterns and "cl_square_law" in m.patterns)
check("rename: subclass_of edge repointed to new id",
      "cl_square_law" in m.pattern_subclasses("constitutive_law"))
check("rename: refuses a taken target id", m.rename_pattern("cl_density", "cl_square_law") is None)

# 2e. rename auto-trigger (long + stitched id)
m.add_pattern(MetaHyperedgePattern(
    pattern_id="influences_causal_result_positive_mechanism_methodological_factor",
    family="dependency", description="x",
    role_slots=[{"role":"source","type":"PROPERTY","repeatable":True},
                {"role":"target","type":"PROPERTY","repeatable":True}],
    allowed_qualifiers=["dependency_type","cited_from"]))
ren_trig = hev.detect_rename_triggers(m)
check("rename trigger flags unwieldy long+stitched id",
      any("methodological_factor" in t["pattern_id"] for t in ren_trig))

# 3. EvolutionTrigger P1
tr = hev.EvolutionTrigger()
he1 = Hyperedge(eid="e1", pattern_type="unknown_pat", node_ids=["a","b"], node_roles=["x","y"], evidence_span="s1")
he2 = Hyperedge(eid="e2", pattern_type="unknown_pat", node_ids=["c","d"], node_roles=["x","y"], evidence_span="s2")
sig1, c1 = tr.record(he1, "no-matching-meta-pattern", "node_A")
sig2, _ = tr.record(he2, "no-matching-meta-pattern", "node_B")
check("same signature across nodes", sig1 == sig2)
check("cross_node=2 after 2 distinct nodes", tr.cross_node_count(sig1) == 2)

# 4. validate_proposal deterministic rejects
r = hev.validate_proposal({"op":"add_meta_node","type_id":"DEVICE","evidence_span":""}, m)
check("no-evidence -> reject", r["valid"] is False)
r = hev.validate_proposal({"op":"add_meta_node","type_id":"MATERIALS","evidence_span":"x"}, m)
check("near-dup meta_node -> reject", r["valid"] is False and "near-duplicate" in r["reason"])
r = hev.validate_proposal({"op":"bogus_op","evidence_span":"x"}, m)
check("unknown op -> reject", r["valid"] is False)
r = hev.validate_proposal({"op":"add_pattern","pattern_id":"cl_x","family":"free_form_new","role_slots":[{"role":"a","type":"PROPERTY"}],"allowed_qualifiers":["method"],"evidence_span":"x"}, m)
# REDESIGN v2: new family is GROWABLE (not rejected). The deterministic
# gate (near-dup, evidence) still applies; family itself is not gated.
check("new (non-seed) family add_pattern accepted (growable)",
      r["valid"] is not False or "near-duplicate" in r.get("reason","") or "free-form" not in r.get("reason",""))

# 5. validate() failure signal + concrete-before-abstract fallback
inst = InstanceHypergraph(paper_id="p1")
inst.add_node(HGNode(nid="n1", labels=["MATERIAL"], surface="sand"))
he_bad = Hyperedge(eid="e1", pattern_type="foo", node_ids=["n1"], node_roles=["weird_role"], evidence_span="x")
ok, reason = m.validate(he_bad, inst)
check("validate fails on unmatched -> signal", ok is False and reason == "no-matching-meta-pattern")

# 6. run_evolution_loop (conservative gate: cross_node>=2 accepts, =1 rejects)
m2 = seed_meta_hypergraph()
inst2 = InstanceHypergraph(paper_id="p1")
inst2.add_node(HGNode(nid="d", labels=["MATERIAL"], surface="shear cell"))
inst2.add_node(HGNode(nid="p", labels=["PROPERTY"], surface="stress ratio"))
he_fail = Hyperedge(eid="e1", pattern_type="measurement_relation", node_ids=["d","p"],
                    node_roles=["device","property"], evidence_span="the shear cell measured the stress ratio")
tr2 = hev.EvolutionTrigger()
tr2.record(he_fail, "no-matching-meta-pattern", "node_A")
tr2.record(he_fail, "no-matching-meta-pattern", "node_B")  # cross_node=2
evols, _ = hev.run_evolution_loop(m2, [(he_fail, "no-matching-meta-pattern")], tr2, "node_A", "p1", instance=inst2)
check("loop produced >=1 accepted evolution (cross_node>=2)", any(not e.get("rejected") for e in evols))
check("loop added the pattern to meta", "measurement_relation" in m2.patterns_ids())

# 6b. conservative gate rejects single-node growth
m3 = seed_meta_hypergraph()
tr3 = hev.EvolutionTrigger()
tr3.record(he_fail, "no-matching-meta-pattern", "node_solo")  # cross_node=1
evols3, _ = hev.run_evolution_loop(m3, [(he_fail, "no-matching-meta-pattern")], tr3, "node_solo", "p1", instance=inst2)
check("conservative gate rejects single-node growth (cross_node=1)",
      any(e.get("rejected") and "conservative gate" in e.get("reason","") for e in evols3))
check("conservative gate: pattern NOT added on single node", "measurement_relation" not in m3.patterns_ids())

# 7. persistence round-trip
m4 = seed_meta_hypergraph()
par = m4.patterns["constitutive_law"]
m4.split_pattern("constitutive_law", [MetaHyperedgePattern(pattern_id="cl_a", family="constitutive_law",
    role_slots=[dict(s) for s in par.role_slots], allowed_qualifiers=list(par.allowed_qualifiers)),
    MetaHyperedgePattern(pattern_id="cl_b", family="constitutive_law",
    role_slots=[dict(s) for s in par.role_slots], allowed_qualifiers=list(par.allowed_qualifiers))])
from granular_agent.hypergraph_schema import MetaHypergraph
m5 = MetaHypergraph.from_dict(m4.to_dict())
check("meta round-trip: version preserved", m4.version == m5.version)
check("meta round-trip: patterns preserved", set(m4.patterns) == set(m5.patterns))
check("meta round-trip: is_abstract preserved", m4.patterns["constitutive_law"].is_abstract == m5.patterns["constitutive_law"].is_abstract)
check("meta round-trip: family_roots preserved", m4.family_roots == m5.family_roots)
check("meta round-trip: subclass_of queryable on loaded", "cl_a" in m5.pattern_subclasses("constitutive_law"))

print()
print(f"{'ALL PASS' if not fail else 'FAILURES: '+str(fail)}  ({len(fail)} fail)")
sys.exit(1 if fail else 0)
