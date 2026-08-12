# GranularFlow-Bench: A Benchmark Dataset for Structured Extraction from Granular Flow Literature

**Status**: Design draft v2 (2026-08-12). Pre-implementation.
**Branch**: `research/granular-benchmark`
**Worktree**: `LogicKG-benchmark`

**v2 changes**: corrected corpus-scale error (858 is from 2,355 subset, not 10,447); added FUNCTION_RELATION subtype + paper_type (verified on 2022-2024 papers); added markdown-quality diagnostic; recorded 9-paper coverage validation; revised purification method (keyword filter unreliable → survey-citation-layer + LLM semantic).

---

## 1. Motivation

### 1.1 The field is in a multi-mechanism competition phase

Granular flow is less mature than materials science or bioengineering: its core constitutive relations are still contested. Multiple competing frameworks coexist:

- **Rheology laws**: μ(I) rheology (Jop et al. 2006, GDR MiDi 2004) vs non-local rheology (Bouzid 2013, Kamrin 2012, Henann 2016) vs free-volume theory
- **Regime decomposition**: collisional (kinetic theory) / dense (μ(I)) / quasi-static (soil plasticity) — three regimes, each with its own theory (GDR MiDi 2004)
- **Geophysical plasticity**: Coulomb plasticity vs viscoplasticity (Bingham/Casson/Herschel-Bulkley) — "still vigorously debated" (Ancey 2007, verbatim)

This is not a drawback; it is the reason a benchmark is most valuable here. A structured dataset that captures *competing claims about the same physical quantity* enables comparison and verification that no single-schema dataset can. In mature fields, consensus exists to extract; in granular flow, the dataset must represent the competition itself.

### 1.2 Why MuLMS-style flat schemas are insufficient

MuLMS (Friedrich et al. 2023, arXiv 2310.15569) — the closest reference baseline — annotates materials science with 13 entity types (MATERIAL/SAMPLE/DEVICE/NUMERIC/UNIT/PROPERTY/MEASUREMENT...) + measurement-related relations + frames. It stops at setup + results layers.

Granular flow papers go further. Four layers MuLMS cannot represent were verified across four papers of different types (Agnolin 2007 elasticity; Jop 2006 μ(I) rheology; GDR MiDi 2004 classic three-regime; Ancey 2007 geophysical review):

| Element | Example (Jop 2006) |
|---|---|
| FUNCTION_RELATION | μ(I) = μ_s + (μ_2−μ_s)/(1+I_0/I), where I itself = d·√(ρ_s/P)/γ̇ |
| COMPARISON_ARM | collisional / dense / quasi-static regimes |
| CAUSAL_ATTRIBUTION | "dense regime unified by μ(I)" |
| RESEARCH_QUESTION | "constitutive equations for dry granular flows are still debated" |

Crucially, these elements require a **two-dimensional structure**: a FUNCTION_RELATION nests (its argument is another function), is parallel (μ_s, μ_2, I_0 are sibling params), is layered (same law across regimes), and is crossed (validated by multiple experiments). This is exactly the structure LOGOS (arXiv 2509.24294) admits it cannot capture: "hierarchical semantic relations only model static taxonomic structure, does not yet capture richer structures such as causal, temporal, or processual relations."

### 1.3 The gap is real

Literature survey (verified, not title-only):
- "gold extraction + gold QA in the same physical/materials corpus": **no such dataset exists** (verified across arXiv multi-categories + ACL 33k index + venue search, 2022-2026)
- Granular flow / rheology / fluid mechanics / solid mechanics text-extraction datasets: **zero** (these fields' "datasets" are all simulation data, not annotated text)
- Self-evolving schema in scientific IE: AgentCAT (arXiv 2602.18479, chemical catalysis) is the closest competitor, but its ontology is a linear causal lineage (synthesis→descriptors→active sites→macroscopic outcomes), fundamentally different from granular flow's multi-way constitutive coupling. AgentCAT's own limitation: "generalization to other subdomains may require further schema refinement."

---

## 2. Contributions

| # | Contribution | Layer | Risk |
|---|---|---|---|
| C1 | GranularFlow-Bench: first extraction+QA paired gold dataset for granular flow | dataset | floor — publishable regardless |
| C2 | Analysis: why building datasets in physics is harder + how we break through + validity argument | analysis | floor |
| C3 | Schema-evolution × extraction-quality coupling evaluation | method (upper) | ceiling — falsifiable |
| C4 | L3 higher-order schema with 2D structure (nested/parallel/crossed/layered) — the structure LOGOS admits it cannot do | schema innovation | floor+ |

C1+C2+C4 are floor contributions (publishable even if C3 fails). C3 is the ceiling.

---

## 3. Corpus

- **Source corpus**: `颗粒流文献-jhd-两层综述` — 10,447 PDFs (5 core granular-flow surveys + 2-level citation expansion: refs_* + refs_deep_*)
- **Already MinerU-parsed subset**: 2,355 papers (text/markdown), located at `science_evo/.../mineru_2355/`. These 2,355 are a subset of the 10,447.
- **Purification (on the 2,355 subset, prior work)**: keyword filter `granular|discrete element|DEM` ≥10 occurrences → **904 papers, of which 858 have DOI**; 60-paper audit: 66.7% strict granular flow, 86.7% including physics-adjacent. **Keyword filtering is acknowledged as rough** — the 858 still contains ~1/3 non-strict-granular. A better purification (survey-citation-layer + LLM semantic judgment) is planned; see §3.1.
- **Year span**: 1882-2018 (DOI→year 100% recoverable), the only century-spanning granular flow corpus. Median 2004; 75% pre-2010.
- **Note on scale**: 858 is from the 2,355 subset, NOT from filtering the full 10,447. The 10,447 have not yet been filtered; expected yield is higher (refs_* are survey-direct citations = naturally high purity). Filtering the full 10,447 is deferred (see §3.1 — avoid premature large-scale processing before method validation).

### 3.1 Purification method (revised — keyword filter is unreliable)

The prior `granular|DEM` ≥10 keyword filter has two failure modes: misses papers that use "dense suspension/powder/shear band" without the word "granular"; false-hits on "granular computing/benchmark". Planned replacement:
1. **Survey-citation layer** (refs_*, ~600 papers) — naturally high purity, survey authors pre-filtered. Include directly.
2. **refs_deep_* (~9,800)** — diluted, needs filtering. Use LLM semantic judgment (title+abstract) not keywords.
3. Expert spot-check on a sample.

This uses the survey corpus's native structure (citation layers) rather than blind keyword matching.

---

## 4. Schema Design (v1)

### 4.1 Three-tier higher-order schema

```
L1 Entity layer (borrowable from MuLMS, granular-flow-adapted)
  MATERIAL / SAMPLE / DEVICE / NUMERIC / UNIT / PROPERTY / MEASUREMENT / CONDITION

L2 Relation layer (MuLMS condition_* + extensions)
  measures_property / property_value / condition_environment /
  condition_sampleFeatures / condition_instrument / taken_from

L3 Higher-order layer (granular-flow innovation, 2D structure)
  FUNCTION_RELATION    — function/relation (nestable), with subtype:
    constitutive_law | empirical_scaling | governing_equation | numerical_relation
  COMPARISON_ARM        — comparison group (parallel)
  CAUSAL_ATTRIBUTION    — mechanism attribution (layered)
  RESEARCH_QUESTION    — paper-level anchor

Paper-level:
  paper_type            — rheology | experiment | theory | DEM | review
```

### 4.1.1 Subtype + paper_type rationale (verified 2022-2024)

Coverage validation on 9 papers across 5 types (Agnolin 2007 elasticity; Jop 2006 μ(I); GDR MiDi 2004 three-regime; Ancey 2007 review; Albert 1999 drag-experiment; Cleary 2002 DEM; Alam 1998 stability-theory; Berzi 2014 kinetic-theory; Choi 2005 silo-experiment) + 4 frontier (Blatny 2024 rheology-newmodel; Kim 2023 nonlocal-2nd-order; Hernández-Delfin 2022 shape-competing; Barker 2023 well-posedness-theory) showed:
- All L1/L2/L3 elements present across types (FUNCTION_RELATION/COMPARISON_ARM/CAUSAL_ATTRIBUTION ≥8/9).
- **FUNCTION_RELATION takes different forms per paper type**: constitutive_law (μ(I) rheology), empirical_scaling (drag∝velocity), governing_equation (∂tφ+∇·(φu)=0 in theory papers), numerical_relation (DEM param-result). Mixing them under one type conflates physically different relations → **subtype field required**.
- **Same paper can have multiple FUNCTION_RELATION subtypes** (Blatny 2024 has both constitutive_law and governing_equation).
- **paper_type needed**: theory papers (Barker 2023) have few COMPARISON_ARM; rheology papers (Blatny 2024) have many. L3 element distribution differs by paper type.
- RESEARCH_QUESTION not always explicit (3/9 papers); when absent, annotator infers from title/abstract — annotation-protocol issue, not schema issue.

L3 is *higher-order*: its nodes reference L1/L2 entities (a FUNCTION_RELATION's params point to NUMERIC/PROPERTY), and L3 nodes relate to each other (a FUNCTION_RELATION indexed under different COMPARISON_ARMs). This is the 2D structure.

### 4.2 2D structure via graph (not tree)

A FUNCTION_RELATION node:
- → its parameters (L1 entities)                          [parallel]
- → its argument (may be another FUNCTION_RELATION)       [nested]
- ← indexed by COMPARISON_ARM (same law across arms)      [crossed]
- ← linked by CAUSAL_ATTRIBUTION to a regime               [layered]

Example (Jop 2006):
```
FUNCTION_RELATION: μ(I) = μ_s + (μ_2−μ_s)/(1+I_0/I)
  ├── params: {μ_s, μ_2, I_0}                    # parallel
  ├── argument: FUNCTION_RELATION I = d·√(ρ_s/P)/γ̇   # nested
  │     └── params: {d, ρ_s, P, γ̇}
  ├── applies_in: COMPARISON_ARM[dense_flow]      # layered
  └── validated_by: [shear_test, inclined_plane]   # crossed
```

### 4.3 Why this is novel (occupancy check)

| Dimension | Status | Closest prior |
|---|---|---|
| Schema induction (general) | OCCUPIED | DIAL-KG, AutoSchemaKG, LOGOS, AdaKGC |
| Scientific-paper + schema evolution | PARTIAL | AgentCAT (chemical catalysis, linear lineage) |
| **2D nested/parallel/crossed/layered schema** | **OPEN** | LOGOS admits limitation |
| **Evolution×quality coupling as research question** | **OPEN** | none |
| Granular flow schema induction | EMPTY | 0 hits |

Cannot claim: "invented schema induction" / "invented non-flat schema."
Can claim: granular flow + 2D higher-order schema (LOGOS's gap) + evolution-quality coupling (no prior) + anchor-coupling ontology.

---

## 5. Annotation Pipeline (expert verification, not expert annotation)

```
858 purified papers
    ↓
A. Weak supervision (3 methods fused, compared)
   ├── A1 Multi-LLM voting (Kimi/GLM/Qwen/DeepSeek)
   ├── A2 Ontology-constraint filtering (AI-KG architecture)
   └── A3 Experimental-data anchoring (numeric fields)
    ↓
B. Fusion rules (core method contribution)
   ├── field-type routing: numerics→A3, entities/relations→A1+A2
   ├── disagreement resolution
   └── confidence: 3-agree→high; disagree→downgrade or expert
    ↓
C. Expert verification (100 samples, one batch, gate resource)
   ├── verify disagreement samples → which method right
   ├── verify candidate-gold → confirm/reject
   └── produce final gold + κ
    ↓
D. Weak-supervision method comparison (analysis contribution)
```

Experts verify, do not annotate from scratch. Scale comes from weak supervision; quality from expert verification + fusion rules.

### 5.1 Scale targets

- Full corpus processed by weak supervision: 858 papers
- Expert-verified gold: 100 samples (gate resource, one batch)
- Reference baselines: SciER 106 / MuLMS 50+230 / SOFC 45 — we exceed on domain coverage and century-span

---

## 6. QA Layer (self-built, no circularity)

- Questions: LLM-generated from extracted triples
- Answers: anchored to paper's experimental data (not LLM-fabricated)
- This makes "extraction wrong → QA wrong" — QA score reflects extraction quality

---

## 7. Evaluation: Schema-Evolution × Extraction-Quality Coupling (C3, ceiling)

The core method contribution. Test whether schema evolution trajectory affects extraction quality:

- Inject controlled schema changes (add/remove/restructure L3 elements)
- Measure: does extraction quality (vs gold) track the evolution?
- Compare: AgentCAT's progressive evolution (no coupling measured) vs our measured coupling

Kill point: if extraction quality is invariant to schema evolution, C3 fails (but C1+C2+C4 still stand).

---

## 8. Validity Argument

- Expert κ (100 samples, ref: published floor 20 items/2 annotators passed findings)
- Cross-extractor consistency
- Weak-supervision method comparison table (A1/A2/A3 vs expert gold)
- Perturbation test (inject extraction errors, check QA response — the original falsifiable experiment, now embedded)

---

## 9. Differentiation from Neighbors

| | MuLMS | AgentCAT | Ours |
|---|---|---|---|
| Domain | materials "understudied" | chemical catalysis | granular flow "multi-mechanism competition" |
| Ontology shape | flat entities+relations | linear causal lineage | 2D nested/parallel/crossed/layered |
| Schema | predefined | schema-governed + progressive evolution | higher-order, evolution-quality coupled |
| QA layer | none | none | paired extraction+QA |
| Temporal | none | none | 1882-2018 century-span |
| Annotation | expert full-text 230 | automatic + ~800 papers | weak supervision + expert verification 100 |

---

## 10. Open Questions (for next round)

1. L3 four elements verified on 4 papers; should verify on 1-2 more (e.g., jamming phase-transition type) for full generality?
2. QA self-build: LLM-generated questions + paper-data answers — what's the question-generation protocol to avoid bias?
3. Schema evolution × quality: what's the concrete operationalization of "controlled schema change"?
4. AgentCAT full-text limitations read (§7); need to read DIAL-KG and LOGOS full limitations too for the differentiation section.

---

## 11. Markdown / Formula Quality Diagnostic

**MinerU markdown (2,355 papers)**:
- L1/L2 quality: sufficient. Numerals (157 in Jop 2006), units, terms preserved.
- L3 quality: **insufficient for formulas**. The μ(I) expression itself is broken in the markdown ("the Inertial number: where μ(I) is..." — the equation is dropped). LaTeX commands (`\scriptstyle`, `\mathrm{}`, escaped spaces `\ `) pollute the text; this is the same issue noted in prior work (LaTeX-space caused 7× extraction overcount).

**pypdf direct-from-PDF (formula extraction)**:
- Jop 2006: `µ(I) = µs + (µ2−µs)/(I0/I+1)` — **complete formula recovered**.
- Blatny 2024, Kim 2023, Barker 2023 (frontier): governing equations recovered (`ρ Dρ/Dt + ρ(∇·v)=0`, `A1=2D`, `∂tφ+∇·(φu)=0`) — **good quality on modern PDFs**.
- Conclusion: L3 formula extraction does NOT need a neural formula recognizer (Nougat). pypdf text-layer suffices for digital-native PDFs.

**Caveat (untested)**: PDF text-layer coverage across the 2,355 + 10,447 corpus. Digital-native PDFs (arXiv-era, post-2000) extract well; scanned/legacy PDFs may not. Prior memory notes the local 20-paper set is "all digital-native (CCITT=0/JBIG2=0)", but full-corpus text-layer coverage is unmeasured. **Must verify** before relying on pypdf at scale.

## 12. Asset Locations (this worktree)

- `.research_tmp/granular-benchmark/data/` — SciFact corpus+claims (mechanism validation)
- `.research_tmp/granular-benchmark/mulms_ref/` — MuLMS annotation guidelines PDF
- `.research_tmp/granular-benchmark/schema_survey/` — AgentCAT/DIAL-KG/LOGOS HTML cache
- Survey corpus: `C:/Users/D0n9/Desktop/颗粒流文献-jhd-两层综述/` (10,447 PDFs, shared, not in any worktree)
