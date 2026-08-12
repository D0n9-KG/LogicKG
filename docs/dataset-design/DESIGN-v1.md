# GranularFlow-Bench: A Benchmark Dataset for Structured Extraction from Granular Flow Literature

**Status**: Design draft v4 (2026-08-12). Pre-implementation.
**Branch**: `research/granular-benchmark`
**Worktree**: `LogicKG-benchmark`

**v4 changes**: integrates all experimental results (schema v3 validation, corpus purification 1186, multi-LLM consistency, MARY fusion, ontology/fusion surveys) into one coherent design. Replaces scattered experiment-logs with a unified document.

---

## 1. Motivation

### 1.1 The field is in a multi-mechanism competition phase

Granular flow is less mature than materials science or bioengineering: its core constitutive relations are still contested. Multiple competing frameworks coexist:

- **Rheology laws**: μ(I) rheology (Jop et al. 2006, GDR MiDi 2004) vs non-local rheology (Bouzid 2013, Kamrin 2012, Henann 2016) vs free-volume theory
- **Regime decomposition**: collisional (kinetic theory) / dense (μ(I)) / quasi-static (soil plasticity) — three regimes, each with its own theory (GDR MiDi 2004)
- **Geophysical plasticity**: Coulomb plasticity vs viscoplasticity (Bingham/Casson/Herschel-Bulkley) — "still vigorously debated" (Ancey 2007, verbatim)

This is not a drawback; it is the reason a benchmark is most valuable here. A structured dataset that captures *competing claims about the same physical quantity* enables comparison and verification that no single-schema dataset can.

### 1.2 Why MuLMS-style flat schemas are insufficient

MuLMS (Friedrich et al. 2023, arXiv 2310.15569) — the closest reference baseline — annotates materials science with 13 entity types + measurement-related relations + frames. It stops at setup + results layers.

Granular flow papers go further. Coverage validation on 9 papers across 5 types (Agnolin 2007 elasticity; Jop 2006 μ(I); GDR MiDi 2004; Ancey 2007 review; Albert 1999 drag-experiment; Cleary 2002 DEM; Alam 1998 stability-theory; Berzi 2014 kinetic-theory; Choi 2005 silo-experiment) + 4 frontier 2022-2024 (Blatny 2024; Kim 2023; Hernández-Delfin 2022; Barker 2023) showed 4 elements MuLMS cannot represent:

| Element | Example |
|---|---|
| CONTRIBUTION (reified) | the paper's core scientific contribution, multi-label subtypes |
| CONTRIBUTION_RELATION | directed edges between contributions (supports/conflicts/...) |
| RESEARCH_QUESTION | the paper's research question |
| paper_type | rheology/experiment/theory/DEM/review |

### 1.3 The gap is real (verified)

- "gold extraction + gold QA in the same physical/materials corpus": **no such dataset exists** (verified across arXiv multi-categories + ACL 33k index + venue search, 2022-2026)
- Granular flow / rheology / fluid mechanics text-extraction datasets: **zero** (these fields' "datasets" are all simulation data)
- Self-evolving schema in scientific IE: AgentCAT (arXiv 2602.18479, chemical catalysis) is the closest competitor, but its ontology is a linear causal lineage, fundamentally different from granular flow's multi-way constitutive coupling. AgentCAT's own limitation: "generalization to other subdomains may require further schema refinement."

---

## 2. Contributions

| # | Contribution | Layer | Risk | Status |
|---|---|---|---|---|
| C1 | GranularFlow-Bench: first extraction+QA paired gold dataset for granular flow | dataset | floor — publishable regardless | corpus purified (1186 papers) |
| C2 | Analysis: why building datasets in physics is harder + how we break through + validity argument | analysis | floor | schema validated on 13 papers |
| C3 | Schema-evolution × extraction-quality coupling evaluation | method (upper) | ceiling — falsifiable | deferred to post-gold (C3 experiment inconclusive due to confounds) |
| C4 | L3 higher-order schema with 2D structure (contribution-centric, reified) | schema innovation | floor+ | v3 formal JSON Schema + extraction-validated |
| C5 | Weak-supervision fusion: MARY + SudokuFill + Conformal + ontology-as-arbiter | method | floor+ | MARY validated, rest pending |

C1+C2+C4+C5 are floor contributions (publishable even if C3 fails). C3 is the ceiling.

---

## 3. Corpus

- **Source corpus**: `颗粒流文献-jhd-两层综述` — 10,447 PDFs (5 core granular-flow surveys + 2-level citation expansion)
- **Already MinerU-parsed subset**: 2,355 papers (markdown), at `science_evo/.../mineru_2355/`
- **Purification (LLM semantic, not keyword)**: classified all 2,355 titles via deepseek-chat → **1186 yes (50%) / 919 no (39%) / 250 unclear (11%)**
- **Subdomain distribution** (of 1186): theory 408 / experiment 401 / DEM 111 / rheology 100 / geophysical 71 / simulation 52 / other 43
- **Year span**: 1882-2018 (DOI→year 100% recoverable), the only century-spanning granular flow corpus
- **Purified corpus list**: `.research_tmp/granular-benchmark/purified_corpus_1186.jsonl` (commit ab2eeb6e)
- **Note**: 50% purity means ~593 are strict granular flow (LLM yes + high confidence); expert verification will trim non-granular from the 100-sample gate.

---

## 4. Schema Design (v3, contribution-centric)

Formal definition: `schema/granular_flow.schema.json` (validated: legal instance passes, illegal rejected, multi-label subtypes work).

### 4.1 Three-tier higher-order schema

```
L1 Entity layer (borrowable from MuLMS, granular-flow-adapted)
  MATERIAL / SAMPLE / DEVICE / NUMERIC / UNIT / PROPERTY / MEASUREMENT / CONDITION

L2 Relation layer (MuLMS condition_* + extensions)
  measures_property / property_value / condition_environment /
  condition_sampleFeatures / condition_instrument / taken_from

L3 Contribution layer (granular-flow innovation, 2D structure)
  RESEARCH_QUESTION    — paper-level anchor
  CONTRIBUTION         — reified first-class entity (not an edge), multi-label subtypes:
    constitutive_law | experimental_finding | mechanism_analysis |
    theoretical_result | numerical_finding | integrative
  CONTRIBUTION_RELATION — directed edges between contributions:
    supports | conflicts | depends_on | applies_in | derives_from

Paper-level:
  paper_type            — rheology | experiment | theory | DEM | review | other
```

### 4.2 Design grounding (survey, not invented)

| Borrowed from | What |
|---|---|
| SciClaim (2021.emnlp-main.381) | CONTRIBUTION as reified entity (association reification); multi-label attributes |
| Matter-of-Fact (2025.emnlp-main.203) | 2D classification; `integrative` 6th subtype; temporal-cutoff backtesting |
| HyperRED (2022.emnlp-main.688) | CONTRIBUTION_RELATION edges carry qualifiers (hyper-relational) |
| MAGIC (2025.findings-emnlp.466) | conflicts as first-class graph structure, not post-hoc detection |
| Complex Event Schema (EMNLP 2021) | non-flat graph schema precedent |

### 4.3 v3 extraction validation (8 papers, first real extraction)

- **Key win**: experiment-drag's 13 FUNCTION_RELATION (v2 abuse) → 3 experimental_finding + 2 mechanism_analysis (v3 correct). The formula-centric L3 was wrong; contribution-centric is right.
- silo-experiment: **4 `conflicts` detected** — multi-mechanism competition surfaced as graph structure.
- integrative (6th subtype) used on DEM/review papers.
- 8/8 L3 non-empty. All subtypes + paper_type appeared.
- Known issue: theory papers occasionally mislabeled as experimental_finding (prompt issue, not structural).

---

## 5. Weak-Supervision Annotation Pipeline

### 5.1 Multi-LLM extraction probe (validated)

- 4 LLMs tested (Kimi-K2.6 / Qwen3.5-27B / DeepSeek / GLM-5-Turbo), 10 papers, schema v3
- **GLM-5-Turbo: 6/10 returned 0 atoms → dropped**
- **DeepSeek: 3/10 returned 0 (long-text timeout) → usable with retry/length-cap**
- **Kimi + Qwen: 10/10 success, atom-count ratio 1.1-1.4x → schema v3 comprehensible across LLMs**
- Entity Jaccard 0.09-0.46 → low overlap, **majority voting not applicable**

### 5.2 MARY fusion (validated, direction)

- Tested on 9 papers (Kimi+Qwen, 460 union entities, 363 minority)
- MARY@0.5 keeps 111/363 minority (31%), prunes 252 (69%) — finds middle ground between union noise and majority-vote loss
- Embeddings via Paratera GLM-Embedding-2 API (no local install, 1024-dim)
- **Threshold 0.5 uncalibrated** — needs expert gate to calibrate

### 5.3 Revised pipeline (survey-grounded)

```
3 LLMs (Kimi + Qwen + DeepSeek-retry, GLM dropped)
    ↓
MARY semantic-neighborhood fusion (not voting — overlap too low)
    ↓
SudokuFill anchor propagation (high-confidence anchors lock → constrain dependent slots)
    ↓
Conformal escalation gate (disagreement atoms → conformal prediction → >1 → expert)
    ↓
Ontology-as-disagreement-arbiter (claimable novelty — only arXiv 2606.05206 does this, in neuroscience not granular flow)
    ↓
Tiered gold: high/medium auto-accept; low → expert verification (100 samples, one batch)
```

### 5.4 Expert verification (gate resource)

- 100 samples, one batch (2 domain experts, gate resource — not iterative)
- Calibrate MARY threshold + verify gold + report κ
- Reference baselines: MuLMS 50+230 / SciER 106 / SOFC 45 — our 1186 purified corpus exceeds

### 5.5 Key warnings (from survey)

- Minority Sentinel (arXiv 2606.29270): unconstrained LLM-as-judge has **net negative gain** — do not deploy
- arXiv 2607.08065: frontier models agree≥0.8 but still 48% wrong — 4 LLM consensus ≠ gold, spot-check required
- SynthAVE (2607.07469): 4 LLMs too few; 4 LLM × 3 prompts = 12 configurations improves robustness (κ 0.76→0.92)

---

## 6. QA Layer (self-built, no circularity)

- Questions: LLM-generated from extracted triples
- Answers: anchored to paper's experimental data (not LLM-fabricated)
- This makes "extraction wrong → QA wrong" — QA score reflects extraction quality

---

## 7. Evaluation: Schema-Evolution × Extraction-Quality (C3, deferred)

- First C3 test (commit 8f2c0a39) was inconclusive: atom-count confound (v2 extracted fewer), no L1/L2 vs L3 split, reference-free verifier with known blind spot
- Deferred to post-gold: proper test needs gold-anchored measurement, not reference-free verifier
- C1+C2+C4+C5 stand regardless

---

## 8. Differentiation from Neighbors

| | MuLMS | AgentCAT | Ours |
|---|---|---|---|
| Domain | materials "understudied" | chemical catalysis | granular flow "multi-mechanism competition" |
| Ontology shape | flat entities+relations | linear causal lineage | 2D contribution-centric (reified, multi-label, conflict-as-graph) |
| Schema | predefined | schema-governed + progressive evolution | higher-order, contribution-as-reified-entity |
| QA layer | none | none | paired extraction+QA |
| Temporal | none | none | 1882-2018 century-span |
| Annotation | expert full-text 230 | automatic + ~800 papers | weak supervision (MARY+SudokuFill+Conformal) + expert verification 100 |
| Fusion | n/a | n/a | MARY semantic-neighborhood + ontology-as-arbiter (novelty) |

---

## 9. Claimable Novelty (occupancy-checked)

| Claim | Status |
|---|---|
| Granular flow extraction+QA benchmark | EMPTY (no prior) |
| 2D contribution-centric schema (reified, multi-label, conflict-as-graph) | OPEN (LOGOS admits limitation) |
| Schema-evolution × quality coupling evaluation | OPEN (no prior) — deferred to post-gold |
| Multi-LLM + ontology-as-disagreement-arbiter | OPEN (only arXiv 2606.05206, neuroscience) — claimable |
| Low-overlap multi-LLM fusion in structured scientific IE | OPEN (MUSE/MARY tested on QA/classification, not structured IE) |

**Cannot claim**: "invented schema induction" (DIAL-KG/AdaKGC) / "invented non-flat schema" (Complex Event Schema EMNLP 2021) / "invented weak supervision" (Snorkel/PromptedWS).

---

## 10. Honest Limitations & Validation Status

1. **Schema v3**: extraction-validated on 13 papers (8 old + 4 frontier + 1 repeat), but no expert audit, no κ, no gold — directional only
2. **Corpus purification**: LLM title-only (no abstract, 0% fill), 50% purity — expert gate will trim
3. **MARY fusion**: n=9, threshold uncalibrated, no precision/recall measurement
4. **C3 (schema-evolution × quality)**: inconclusive, deferred
5. **n=8-13 throughout**: small samples, single seed — all conclusions directional
6. **AgentCAT full-text limitations read**; DIAL-KG/LOGOS limitations partially read
7. **Remote MinerU offline** (192.168.199.73) — cannot re-parse 10447; working with 2355 markdown subset

---

## 11. Markdown / Formula Quality

- L1/L2 quality: sufficient (numerals, units, terms preserved in mineru markdown)
- L3 quality: formulas broken in mineru markdown (μ(I) expression dropped; LaTeX commands pollute)
- pypdf direct-from-PDF recovers formulas (Jop 2006: `µ(I)=µs+(µ2−µs)/(I0/I+1)`; Blatny 2024: governing equations) — no Nougat needed for digital-native PDFs
- v3's CONTRIBUTION uses text statements (not precise formulas) — so markdown quality is sufficient for v3

---

## 12. Asset Locations

- `.research_tmp/granular-benchmark/data/` — SciFact corpus+claims (mechanism validation)
- `.research_tmp/granular-benchmark/mulms_ref/` — MuLMS annotation guidelines PDF
- `.research_tmp/granular-benchmark/schema_survey/` — 11 ontology design papers (HTML cache)
- `.research_tmp/granular-benchmark/purified_corpus_1186.jsonl` — purified corpus list
- `.research_tmp/granular-benchmark/multi_llm_extract_results.jsonl` — multi-LLM extraction data
- `.research_tmp/granular-benchmark/mary_fusion_results.jsonl` — MARY fusion results
- Survey corpus: `C:/Users/D0n9/Desktop/颗粒流文献-jhd-两层综述/` (10,447 PDFs, shared)
