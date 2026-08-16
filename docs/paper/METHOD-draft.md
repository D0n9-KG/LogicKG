# Method Section Draft

## 3. Method

We propose a self-evolving meta-hypergraph schema for knowledge graph
construction from scientific literature. The schema itself is a hypergraph
(patterns as meta-hyperedges connecting type-slots, with IS-A taxonomy +
pattern-level dependency/constraint edges), and it evolves during extraction
via five bounded operations (add/split/merge/retire/rename). Unlike prior
schema-evolving KG work (DIAL-KG, AgentCAT, LOGOS), our schema has real
topology — pattern-level dependencies inferred from instances + constraint-
violation detection — enabling a capability DIAL-KG lacks: detecting
structural errors (referenced-but-undefined entities).

### 3.1 Two-Layer Structure

**Schema layer (MetaHypergraph).** The schema is a hypergraph itself, not a
flat predicate set. It contains:
- *Meta-nodes*: entity types (MATERIAL, PROPERTY, NUMERIC, REGIME).
- *Meta-hyperedges (patterns)*: each pattern is a meta-hyperedge connecting N
  type-slots (role→type), defining what a valid instance hyperedge of this
  pattern looks like. Patterns carry qualifiers (condition/method/evidence/
  cited_from/applies_in_regime/dependency_type) as controlled extension points.
- *Meta-edges*: three kinds — `subclass_of` (IS-A taxonomy, pattern-level),
  `depends_on` (pattern A references entities pattern B defines), and
  `split_from` (lineage). The `depends_on` edges give the schema real topology
  beyond the IS-A tree — DIAL-KG's flat schema has no pattern-level dependencies.

**Instance layer (InstanceHypergraph).** Each paper produces an instance
hypergraph: n-ary hyperedges (arity 2-7) connecting N nodes, each with a
functional role (output/input/source/target/...) + qualifiers + verbatim
evidence. Instance hyperedges are validated against the schema's patterns.

### 3.2 Five Bounded Operations + Conservative Gate

The schema evolves via five operations during extraction:
1. *add_pattern*: new relation class (gated by conservative gate, see below)
2. *split_pattern*: top-down decomposition of an over-wide pattern into
   sub-patterns (the operation DIAL-KG/AgentCAT/LOGOS do NOT do — they only
   merge/retire bottom-up). Parent becomes abstract (kept as generalization),
   children inherit its role-structure + dependency edges.
3. *merge_patterns*: canonicalize near-duplicate patterns (DIAL-KG's op,
   reimplemented on hypergraph schema)
4. *retire_pattern*: soft-deprecate orphan/empty patterns
5. *rename_pattern*: shorten unwieldy pattern ids

**Conservative gate** (AgentCAT's "strictly necessary" principle): a growth
op (add_pattern/add_meta_node/add_subclass) is accepted only when the
structural gap recurred across ≥2 DAG nodes OR ≥3 cumulative failures
(cross-paper accumulation for small corpora). This prevents one-off extraction
errors from bloating the schema. The gate is deterministic (not LLM-judged,
breaking the A4 circularity).

### 3.3 Pattern-Level Dependency + Constraint Violation Detection

**Pattern dependency inference** (deterministic, graph reachability): if
pattern A's instance edge references a node that also appears in a definition-
family pattern B's edge, then A `depends_on` B (A uses an entity B defines).
This is inferred from instances, not LLM-judged — the A4 circularity is
preserved.

**Constraint violation detection** (DIAL-KG-can't-do capability): a
NUMERIC node (parameter/constant) referenced by a non-definition pattern
edge but not defined by any definition-family edge = a constraint violation
(referenced-but-undefined entity). This is deterministic (graph reachability)
and quantifiable (violation rate = violations / edges).

Example: a constitutive_law edge references exponent "2" but no definition
edge defines it → violation detected. This exposes real schema gaps
(parameters used without definition).

### 3.4 Growable Families + Qualifiers (Relaxed Locks)

Unlike the original 6-family lock (which forced non-physical relations into
wrong slots), families and qualifier keys are now GROWABLE:
- A new family's first pattern auto-becomes its root (family_roots).
- New qualifier keys can be proposed by the evolution probe (registered
  dynamically).
- Divergence is prevented by the conservative gate + merge/retire, NOT by
  locking families. Seed-sensitivity tests (§4.3) confirm content-driven
  growth: a 2-family seed grows to 4 families (composition/definition
  content-activated), with 0.86-0.98 semantic overlap with a 6-family seed.

### 3.5 Split Topology Inheritance

When a pattern is split, children inherit the parent's `depends_on` edges —
the topology is not lost. A child of a pattern that depends_on `definition`
also depends_on `definition` (it's a specialization of the same relation).
