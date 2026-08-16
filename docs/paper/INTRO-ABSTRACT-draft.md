# Abstract + Introduction Draft

## Abstract

LLM-based knowledge graph construction from scientific literature typically
relies on flat, schema-free extraction (EDC) or bottom-up schema evolution
(DIAL-KG). These approaches lack pattern-level topology — schemas are flat
predicate sets or simple IS-A trees — and cannot detect structural errors
like referenced-but-undefined entities. We propose a self-evolving meta-
hypergraph schema where (1) the schema itself is a hypergraph (patterns as
meta-hyperedges connecting type-slots, with IS-A taxonomy + pattern-level
dependency edges), (2) it evolves via five bounded operations including
pattern-level split (top-down decomposition, which DIAL-KG, AgentCAT, and
LOGOS do not perform), and (3) it detects constraint violations — referenced-
but-undefined numeric parameters — a capability no prior schema-evolving KG
work offers. Families and qualifiers are growable (not locked), with divergence
prevented by a conservative gate + merge/retire rather than hard locks.
On 4 granular-flow papers, the system infers 50 pattern dependencies, detects
38 constraint violations (verified as real, not false-positives), and achieves
0.917 n-ary QA correct rate. Seed-sensitivity tests confirm content-driven
growth (0.86-0.98 semantic overlap across different seeds).

## 1. Introduction

Scientific knowledge graph (KG) construction from research papers is essential
for downstream tasks like literature-based discovery, hypothesis generation,
and scientific reasoning. Recent LLM-based approaches (EDC, DIAL-KG, AgentCAT)
extract triples and induce schemas automatically, but their schemas have
limited structural expressiveness:

**Problem 1: Flat schema topology.** DIAL-KG's schema is a normal graph
(binary relation schemas reified to triples). AgentCAT uses a property graph
with add-only evolution. LOGOS uses a binary typed graph. None have pattern-
level dependencies, constraints, or the ability to detect when an extracted
relation references an entity that was never defined — a structural error
analogous to an undefined variable in code.

**Problem 2: Bottom-up only.** All prior schema-evolving work grows the schema
bottom-up (add/merge/retire). When a pattern becomes over-wide (conflating
different relation types), no operation refines it top-down into specialized
sub-patterns. The schema either bloats or stays coarse.

**Problem 3: Rigid locks.** Fixed top-level families and controlled qualifier
vocabularies prevent divergence but also prevent capturing relations that
don't fit the pre-defined categories — information loss.

We address these with a self-evolving meta-hypergraph schema:
- **Schema as hypergraph**: patterns are meta-hyperedges (connecting N type-
  slots), with IS-A taxonomy + pattern-level dependency edges (inferred from
  instances via graph reachability, deterministic). This gives the schema real
  topology beyond flat predicates.
- **Pattern-level split**: top-down decomposition of over-wide patterns into
  sub-patterns (parent becomes abstract, children inherit topology). This is
  the operation DIAL-KG/AgentCAT/LOGOS do not perform.
- **Constraint violation detection**: a NUMERIC node referenced by a non-
  definition pattern but not defined by any definition edge = a structural
  error (referenced-but-undefined). Detected deterministically (graph
  reachability, no LLM judgment).
- **Growable families + bounded operations**: families and qualifiers are
  growable (not locked to 6), with divergence prevented by conservative gate
  (cross-node recurrence ≥2 OR cumulative ≥3) + merge/retire.

**Contributions:**
1. Self-evolving meta-hypergraph schema with pattern-level dependency topology
   + constraint violation detection (DIAL-KG/AgentCAT/LOGOS lack both).
2. Pattern-level split (top-down, inherited topology) — the operation no
   prior schema-evolving work does.
3. Growable families + qualifiers with conservative gate (content-driven,
   seed-robust).
4. Evaluation on 4 granular-flow papers: 50 dependencies, 38 constraint
   violations (verified real), 0.917 n-ary QA correct rate, seed sensitivity
   (0.86-0.98 overlap).

**Limitations (honest):** No gold precision/recall (requires expert
annotation); single seed (DeepSeek-V3, non-deterministic); WebNLG single-
sentence not suited (schema-free setting); grounding OCR-bound on equation-
dense papers.
