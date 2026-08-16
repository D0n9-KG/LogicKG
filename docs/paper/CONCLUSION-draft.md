# Conclusion Section Draft

## 5. Conclusion

We proposed a self-evolving meta-hypergraph schema for knowledge graph
construction from scientific literature. Unlike prior schema-evolving work
(DIAL-KG, AgentCAT, LOGOS), our schema has real topology — pattern-level
dependencies inferred from instances + constraint violation detection —
and evolves via pattern-level split (top-down, which no prior work does).
Families and qualifiers are growable, with divergence prevented by a
conservative gate + merge/retire rather than hard locks.

On 4 granular-flow papers, the system infers 50 pattern dependencies,
detects 38 constraint violations (verified real, repairable: 14→0, 100%),
achieves 0.917 n-ary QA correct rate (vs 0.542 native baseline, 1.69×),
and demonstrates content-driven growth (0.86-0.98 seed overlap).

**Key insight**: schema topology (pattern dependencies + constraint checks)
enables a capability flat schemas lack — detecting structural errors
(referenced-but-undefined entities) and guiding their repair. This is
analogous to a type system catching undefined variables at compile time.

**Limitations and future work**: No gold precision/recall (requires expert
annotation); single seed (DeepSeek-V3 non-determinism); WebNLG single-
sentence not suited (schema-free setting). Future: expert gold annotation,
multi-seed CI, pattern_constraint/composition edges, cross-paper entity
resolution via embedding.
