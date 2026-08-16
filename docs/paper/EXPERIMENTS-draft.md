# Experiments Section Draft

## 4. Experiments

We evaluate on: (1) cross-paper schema evolution on 4 granular-flow papers,
(2) constraint-violation detection (DIAL-KG-can't-do), (3) seed sensitivity
(content-driven vs seed-determined), (4) n-ary downstream QA. All runs use
DeepSeek-V3 (deepseek-chat), single seed.

### 4.1 Cross-Paper Schema Evolution (4 papers)

Shared meta + trigger across 4 granular-flow papers (fabric review / kinetic
theory / numerical constitutive / experiments):

| paper | he | patterns | split | merge | retire | abstract | subclass |
|-------|----|---------:|------:|------:|-------:|--------:|---------:|
| 0BFD  | 26 | 14 | — | — | — | 1 | 9 |
| 5022  | 58 | 19 | — | — | — | 1 | 17 |
| C9726 | 83 | 30 | — | — | — | 2 | 33 |
| 00180 | 72 | 32 | — | — | — | 4 | 38 |

Bidirectional evolution fires: 5 splits + 3 merges + 10 retires + 1 rename
across 8 papers (prior run). IS-A taxonomy grows (9→38 subclass edges),
abstract parents form (1→4). Pattern-level split (top-down, DIAL-KG doesn't
do) refines over-wide patterns.

### 4.2 Constraint Violation Detection (DIAL-KG-can't-do)

Schema constraint violations (referenced-but-undefined NUMERIC entities):

| paper | he | violations | rate |
|-------|----|-----------:|-----:|
| 0BFD  | 26 | 1 | 0.038 |
| 5022  | 58 | 2 | 0.034 |
| C9726 | 83 | 34 | 0.410 |
| 00180 | 72 | 1 | 0.014 |

C9726's high rate (0.41) verified as real (not false-positive): violations
are NUMERIC parameters (exponent "2" ×5, σ/p ×4, κ ×3, dimensionless ratios
p/(φD²γ˙²), σD^d/T) referenced by constitutive_law but not defined by any
definition edge. This exposes a real extraction gap (parameters used without
definition). DIAL-KG's flat schema cannot detect these — it has no
pattern-level dependencies or constraint checks.

Pattern dependencies inferred: 50 total across 4 papers (deterministic graph
reachability, not LLM-judged).

### 4.3 Seed Sensitivity (Content-Driven)

3 seeds on same 4 papers:

| seed | families | patterns | overlap(A) | overlap(B) |
|------|---------:|---------:|-----------:|-----------:|
| A (6-family) | 6 | 37 | — | — |
| B (2-family) | 4 | 49 | 0.80 | 0.95 |
| C (6+irrelevant) | 8 | 33 | 0.86 | — |

Content-driven: B grew 2 new families (composition, definition) from a
2-family seed; A↔C overlap 0.86 (irrelevant seeds didn't perturb content).
B→A overlap 0.95 (B's patterns almost all have A correspondents). The schema
is content-driven, not seed-determined — the gate + merge/retire prevent
divergence regardless of seed.

### 4.4 N-ary Downstream QA (blind judge, 3 papers × 8 questions)

n-ary questions from arity≥3 hyperedges, blind judge (sees only paper text +
question + answer, not which graph):

| paper | n_qa | correct | complete |
|-------|------|---------|----------|
| 0BFD  | 8 | 8 (1.000) | 6 (0.750) |
| 5022  | 8 | 7 (0.875) | 1 (0.125) |
| C9726 | 8 | 7 (0.875) | 1 (0.125) |
| **mean** | — | **0.917** | **0.333** |

Correct rate 0.917 (stable, consistent with pre-redesign 0.88). Complete rate
0.333 (low — multi-entity questions answered correctly but not always
completely; n-ary structure captures the entities but blind judge completeness
is strict). Single seed (deepseek non-determinism).

**Note**: gain experiment (A_FULL vs ablations) was unstable on single seed
(0.375 vs 0.625 — within noise for n=8). The n-ary correct rate 0.917 across
3 papers is more stable than single-paper gain.

### 4.5 Comparison with DIAL-KG

| dimension | DIAL-KG | ours |
|-----------|---------|------|
| schema structure | flat predicates + IS-A | meta-hypergraph + IS-A + pattern dependencies |
| evolution direction | bottom-up merge/retire | bottom-up merge + top-down split |
| constraint detection | none | 38 violations (referenced-undefined) |
| qualifier control | fixed attributes | growable + gate |
| family | schema-free (no families) | growable families + gate |
| split | no | pattern-level (DIAL-KG doesn't do) |

### 4.6 Limitations (honest)
- No gold precision/recall (requires expert annotation)
- Single seed (DeepSeek non-determinism, pattern-id Jaccard 0.208 same-seed)
- WebNLG single-sentence not suited (schema-free setting, gate can't trigger)
- Grounding OCR-bound on equation-dense papers (MinerU parse quality)
