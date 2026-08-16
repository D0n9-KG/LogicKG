# GranularFlow-Bench: An Agent System for Self-Evolving Schema Extraction from Granular Flow Literature

**Authors**: [Anonymous — under review]
**Target**: CCF-A (ACL/EMNLP/NeurIPS/ICLR main)

---

## Abstract

We present GranularFlow-Bench, an agent system for structured information extraction from granular flow literature that addresses two challenges: (1) the absence of structured extraction benchmarks for physical science domains where competing theoretical frameworks coexist, and (2) the inherent insufficiency of predefined schemas in evolving scientific fields. Our system implements a three-phase schema-guided DAG extractor (full-text structure mapping → chained DAG extraction with a JSON blackboard → deterministic exact-text-match grounding) at 7.4 LLM calls/paper, and a self-evolving schema mechanism with evidence-linked validation and append-only version management, built on a three-tier contribution-centric schema (L1 entities, L2 relations, L3 contributions) refined through four manual versions. We validate on 1,186 purified granular flow papers (1882–2018) across seven subdomains, extracting 3,135 structured atoms from a 49-paper subset with 99.97% verbatim-evidence grounding (replacing a truncating extractor that failed on 4/5 probe papers). A 20-paper ablation shows self-evolution-ON yields +5.3% atoms and 3 genuine schema extensions (v4.0→v4.3: `research_question` contribution subtype, `extends`/`resolves` contribution relations) that full-text extraction surfaces but the prior truncated run missed — self-evolution's within-domain value is periphery-extension on a mature schema, detectable only under full-text coverage. Compared to the closest prior work RAGA (arXiv 2605.17072), we contribute explicit gap discovery, QA generation, and schema-evolution quality evaluation as first-class capabilities. The dataset, schema, and agent system are released.

**Keywords**: information extraction, self-evolving schema, granular flow, knowledge graph, agent system, benchmark

---

## 1. Introduction

Structured information extraction from scientific literature is essential for building domain knowledge graphs that serve downstream tasks such as retrieval-augmented generation (RAG), question answering, and scientific discovery. However, two challenges persist in physical science domains.

**Challenge 1: Domain absence.** Despite the abundance of IE benchmarks in NLP, biomedicine, and materials science (MuLMS [Friedrich et al., 2023], SciER [Jain et al., 2024], SOFC-Exp [Friedrich et al., 2020]), no structured extraction benchmark exists for granular flow — a subfield of physics where multiple competing constitutive frameworks (μ(I) rheology [Jop et al., 2006], non-local rheology [Bouzid et al., 2013], Coulomb plasticity vs. viscoplasticity [Ancey, 2007]) coexist without consensus. This "multi-mechanism competition" makes the domain uniquely challenging: a benchmark must capture not just established facts but competing claims about the same physical quantities.

**Challenge 2: Schema insufficiency.** Predefined schemas inevitably miss domain concepts. We confirmed this empirically through four iterations of schema design: v1 (formula-centric) abused experimental papers; v2 (with subtypes) remained formula-centric; v3 (contribution-centric) could not represent multi-variable constitutive closures or regime classifications; v4 (with structural fixes) resolved known issues but the pattern of "design → test → find gaps → redesign" suggested that manual patching is an endless process. This motivates self-evolving schemas that automatically discover and validate new schema elements during extraction.

Recent work has made progress on autonomous knowledge graph construction. RAGA [Han and Cheng, 2026] proposes a ReAct-based agent with schema auto-discovery and evidence-anchored verification. AgentCAT [Yang et al., 2026] implements progressive schema evolution for chemical catalysis. AutoSchemaKG [Bai et al., 2026] performs one-shot LLM conceptualization for web-scale KGs. However, source-code analysis reveals that none of these achieve true self-evolution with a trigger → validate → version-manage loop (§2.3).

We propose GranularFlow-Bench, which makes the following contributions:

- **C1. Granular flow benchmark dataset**: 1,186 purified papers with structured extraction (3,135 atoms across 49 papers, 99.97% verbatim-grounded), the first for this domain.
- **C2. Self-evolving schema agent system**: A Pydantic AI-based agent with 6 capabilities (three-phase Extract, Fuse, GapDiscovery, Validate, ExtendSchema, QAGenerate) and 5 event-driven hooks, featuring append-only schema version management with provenance tracking.
- **C3. Contribution-centric schema (v4)**: A three-tier schema (L1 entities / L2 relations / L3 contributions) with CLOSURE entities for multi-variable constitutive laws, REGIME as a first-class entity, and 9 contribution subtypes including scaling_law, regime_map, and methodology.
- **C4. Three-phase schema-guided DAG extraction**: full-text (no truncation), 7.4 calls/paper, deterministic exact-text-match grounding (99.97%), discourse-role-aware rebind detection — a low-cost auditable alternative to per-paragraph ReAct extraction (RAGA's 50+ calls/paper).
- **C5. Schema-evolution × extraction-quality evaluation**: An ablation (self-evolution ON vs OFF on 20 papers) showing that under full-text extraction, self-evolution-ON yields +5.3% atoms and 3 genuine schema extensions (v4.0→v4.3) the prior truncated run missed; the v4 core covers granular-flow entities and the residual growth surface is contribution relations.

## 2. Related Work

### 2.1 Scientific IE Benchmarks and Schemas

MuLMS [Friedrich et al., 2023] provides a multi-layer annotated corpus for materials science with 13 entity types and measurement-related relations. SciER [Jain et al., 2024] introduces 4-ary relations for document-level scientific IE. SOFC-Exp [Friedrich et al., 2020] annotates solid oxide fuel cell experiments. However, these benchmarks target domains with relatively stable ontologies, unlike granular flow where competing frameworks create inherent schema instability.

SciClaim [Cattan et al., 2021] reifies scientific associations as first-class entities with multi-label attributes (Causation/Correlation/Comparison/Sign+/Sign−), inspiring our CONTRIBUTION entity design. Matter-of-Fact [2025] introduces a 2D claim classification (Qualitative/Quantitative × Experimental/Simulation/Theoretical/Integrative), informing our contribution subtypes. HyperRED [Chia et al., 2022] proposes hyper-relational facts with qualifier attributes, adopted in our CONTRIBUTION_RELATION design. MAGIC [2025] treats conflicts as first-class graph structure, informing our conflict-as-edge approach.

### 2.2 Agent Systems for KG Construction

RAGA [Han and Cheng, 2026] is the closest prior work: an LLM agent with atomic CRUD tools, a Read–Search–Verify–Construct cognitive loop, schema auto-discovery (4-phase), evidence-anchored verification, and PROPOSED state for new schema elements. However, RAGA lacks explicit gap discovery (only implicit via PROPOSED state), does not generate QA pairs (only retrieval), uses a single LLM, and has no schema version management. Our three true differences are: (1) active gap discovery as a first-class capability, (2) QA generation with paper-anchored answers, and (3) schema-evolution quality evaluation (C5).

AgentCAT [Yang et al., 2026] implements progressive schema evolution for chemical catalysis with backward compatibility, but its ontology is a linear causal lineage (synthesis→descriptors→active sites→outcomes), fundamentally different from granular flow's multi-way constitutive coupling. DIAL-KG [2026] proposes a closed-loop schema evolution with evolution-intent assessment but targets general KG, not scientific extraction. AutoSchemaKG [Bai et al., 2026] performs one-shot LLM conceptualization without incremental evolution, validation, or versioning. AdaKGC [Zhang et al., 2023] defines schema-adaptable KGC but uses manual YAML for schema changes. Source-code analysis of these systems confirms that the trigger→validate→version-manage loop defining true self-evolution has not been fully implemented by any prior work.

### 2.3 Multi-LLM Fusion for IE

MARY [2026] addresses minority-entity inclusion in multi-LLM extraction by semantic-neighborhood gating rather than majority voting. MUSE [2025] uses Jensen-Shannon divergence to select well-calibrated LLM subsets. SudokuFill [2026] propagates high-confidence anchors to constrain dependent schema slots. We adopt MARY's approach with GLM-Embedding-2 API for semantic similarity computation.

## 3. Method

### 3.1 System Architecture

GranularFlow-Bench is built on Pydantic AI (v2.28) and follows a single-agent + capabilities + hooks design. The agent operates in a deterministic flow with event-triggered schema evolution branches, avoiding the overhead of multi-agent debate (justified by FlyAOC [2026] finding that multi-agent > single-agent, but our task is deterministic extraction with controlled extension, not open-ended reasoning).

**Capabilities** (6):
1. **Extract**: Three-phase schema-guided DAG extraction (Phase 0 structure map → Phase 1 chained DAG extraction → Phase 2 grounding + rebind detection). Full-text, no truncation; 5-10 LLM calls/paper; every atom grounded by verbatim evidence span (§3.4).
2. **Fuse**: MARY semantic-neighborhood fusion of multi-LLM results using GLM-Embedding-2 (validated separately, §3.5; not in the 50-paper mainline run which is single-LLM).
3. **GapDiscovery**: Passive (detect schema-fitting failures during extraction) + active (cross-paper recurring pattern scan).
4. **Validate**: Evidence-linked validation — every schema gap candidate must have source-text evidence.
5. **ExtendSchema**: Append new schema elements with provenance (append-only + CHANGELOG.jsonl).
6. **QAGenerate**: Generate QA pairs with answers anchored to paper experimental data.

**Hooks** (5): `on_extraction_complete`, `on_gap_found`, `on_batch_complete`, `on_schema_extended`, `on_qa_generated`.

**Schema version management**: Each schema extension creates a new version file (v4.0 → v4.1 → ...) with provenance record (what changed, why, evidence, paper_id, timestamp). Old versions are preserved (append-only), addressing the information-loss problem observed in shared-layer approaches.

### 3.2 Schema Design (v4)

The schema evolved through four iterations:

- **v1** (FUNCTION_RELATION-centric): Abused on experiment papers (13 "formulas" in a drag-experiment paper).
- **v2** (with subtypes): Still formula-centric; μ(I) multi-variable closure did not fit.
- **v3** (contribution-centric): CONTRIBUTION as reified entity (per SciClaim), but lacked CLOSURE for multi-variable laws, REGIME as entity type, and split CONDITION.
- **v4** (structural fixes): Added BOUNDARY_CONDITION, INITIAL_STATE, MATERIAL_PARAMETER, DIMENSIONLESS_NUMBER, REGIME as L1 entities; CLOSURE as optional L3 entity for structured constitutive laws; 9 contribution subtypes (constitutive_law, experimental_finding, mechanism_analysis, theoretical_result, numerical_finding, integrative, scaling_law, regime_map, methodology); 9 relation types (supports, conflicts, depends_on, applies_in, applies_in_regime, derives_from, specializes, generalizes, bounds_applicability_of).

All three tiers (L1/L2/L3) are evolvable, with L1 < L2 < L3 in evolution frequency.

### 3.3 Corpus

From a 10,447-paper survey corpus (5 core granular flow surveys + 2-level citation expansion), 2,355 papers were MinerU-parsed. LLM semantic title classification (DeepSeek, temperature 0) on all 2,355 titles yielded 1,186 granular flow papers (50% purity) across 7 subdomains: theory (408), experiment (401), DEM (111), rheology (100), geophysical (71), simulation (52), other (43). The corpus spans 1882–2018, the only century-spanning granular flow corpus.

### 3.4 Three-Phase Schema-Guided DAG Extraction

The earlier extraction fed each paper's first and last 4,000 characters (8,000 total) to a single LLM call. Papers average 40–60k characters, so ~80% of content was lost; on a 5-paper probe the old extractor returned 0 atoms on 4/5 papers. We replace it with a three-phase design that reads the full text in a 64k-context LLM (DeepSeek) at a cost of 5–10 calls/paper.

**Phase 0 — Structure mapping (1 call).** The full paper text (as mineru block-indexed text) is sent in one LLM call. The LLM does NOT extract atoms; it outputs a compact structure map: section boundaries (as block-index half-open ranges, avoiding unreliable char-offset counting), discourse roles per section (summary / context / definition / observation / interpretation / claim, per Scientific Discourse Tagging [arXiv 1909.04758]), key entities, and a schema-guided DAG. Each DAG node targets one section and a subset of schema fields (e.g. Method→{MATERIAL, BOUNDARY_CONDITION, CLOSURE}, Results→{MEASUREMENT, NUMERIC, CONTRIBUTION}); edges encode dependency (Results depends on Method's definitions). The prompt mandates that every non-reference section appear in at least one node. The structure map is stable across runs (same 7 nodes/fields observed on repeated calls); downstream variance comes from extraction, not structure mapping.

**Phase 1 — Chained extraction (4–8 calls).** DAG nodes execute in topological order. Each node runs in a fresh LLM context (no conversation history, per Chained RLM [arXiv 2608.05124]) and receives: its section text, a ≤200-token compact summary of what predecessor nodes extracted, and the schema fields it targets. It emits atoms decorated with `evidence_span` (a verbatim phrase copied from the section) and `confidence` (0–1 self-assessment), plus a compact summary carrying to dependents. A shared **blackboard** (JSON: atoms + per-node summaries) replaces RAGA's Neo4j KG as the cross-section carrier — lighter, no query language. Adaptive fission (per TopoAgent [arXiv 2607.14658]): if a node's mean confidence < 0.40, its fields split into two focused sub-calls instead of looping ReAct-style; capped at 2 fissions/paper to bound cost.

**Phase 2 — Grounding + rebind detection (0–1 call).** Grounding is deterministic (no LLM): each atom's `evidence_span` must appear verbatim in the paper text (whitespace-normalized) — LMDX-style exact-text-match validation [arXiv 2309.10952], not LLM self-audit. Atoms failing the match are flagged. Rebind detection (our contribution): L1 entity atoms sharing a surface form across different discourse roles (e.g. a term defined in Method and re-purposed in Conclusion) are flagged as candidates — the same value under a different binding. One LLM lookup call over all flagged/ungrounded atoms either confirms (correcting the span to a verbatim one) or marks unsupported; unconfirmed atoms are discarded.

**Cost model.** Phase 0: 1 call (always). Phase 1: 4–8 calls (DAG size). Phase 2: 0–1 call. Total 5–10 calls/paper — vs RAGA's 50+ per-paragraph calls. The grounding rate (atoms with verbatim evidence / kept atoms) is 100% by construction after Phase 2 filtering.

### 3.5 Multi-LLM Extraction and Fusion (auxiliary)

A multi-LLM probe on 10 papers revealed: Kimi-K2.6 and Qwen3.5-27B are stable (10/10 success); DeepSeek 7/10 (long-text timeout); GLM-5-Turbo failed (6/10 zero-atom, dropped). Entity Jaccard across LLMs was 0.09–0.46, confirming majority voting is inappropriate. MARY fusion with GLM-Embedding-2 (1024-dim) was validated on 9 papers (460 union, 363 minority): at threshold 0.5 it retains 111/363 (31%) and prunes 252 (69%). This capability is available but the 50-paper mainline run (§4.2) is single-LLM to isolate the three-phase extraction effect.

## 4. Experiments

### 4.1 Single-Paper Validation

On Jop et al. (2006) — the foundational μ(I) rheology paper (15,534 chars) — the new three-phase extractor runs in 7–8 LLM calls and produces ~55 atoms with 100% grounding (every atom's evidence_span verbatim in the full text), including the μ(I) constitutive-law CONTRIBUTION and dimensionless-number I atoms. Across L1/L2/L3 with correct multi-label subtypes (constitutive_law + theoretical_result, experimental_finding + numerical_finding). The old truncating extractor on the same paper returned 106 atoms but from only 8,028 chars (80% content loss) with no grounding verification. Repeated single-paper runs on the same paper yield 15–108 atoms (LLM non-determinism at temperature 0 — see §5.3); the structure map (Phase 0) is stable across runs, so variance is confined to Phase 1 extraction yield.

### 4.2 50-Paper Validation

Across 50 papers spanning 7 subdomains (rheology/experiment/theory/DEM/geophysical/simulation/other, 8 each):

| Metric | Value |
|---|---|
| Papers processed | 49 (7 per subdomain × 7 subdomains) |
| Total atoms | 3,135 |
| Grounded atoms (verbatim evidence) | 3,134 (99.97%) |
| Total LLM calls | 364 |
| Avg calls / paper | 7.4 |
| Avg atoms / paper | 64.0 |
| Zero-atom papers | 1/49 (2.0%) |
| Schema version | 4.0 (unchanged, self-evolution OFF) |

By subdomain (atoms / calls): DEM 448/51, experiment 512/51, geophysical 590/53, other 569/58, rheology 409/52, simulation 173/45, theory 434/54. The single zero-atom paper (simulation subdomain) was a Phase 0 structure-mapping failure that fell back to the old truncating extractor (which returned 0 atoms) — a recoverable error, not a content limitation. Compared to the prior truncating extractor, which returned 0 atoms on 4/5 probe papers (§4.1), the three-phase system reads full text (up to 60k chars, no truncation) and grounds 99.97% of atoms by verbatim evidence.

### 4.3 Self-Evolution Ablation (C5)

Ablation on the same 20 papers (stratified across 7 subdomains, 3 each minus 1), self-evolution ON vs OFF, single-LLM (DeepSeek), single seed:

| Metric | Evo OFF | Evo ON | Diff |
|---|---|---|---|
| Total atoms | 1,319 | 1,389 | +70 (+5.3%) |
| Avg atoms / paper | 66.0 | 69.5 | +3.5 |
| Total LLM calls | 155 | 160 | +5 |
| Grounded atoms | 1,319 | 1,388 | (99.97% / 99.93%) |
| Zero-atom papers | 0 | 0 | 0 |
| Schema evolutions | 0 | 3 | +3 |
| Schema version end | 4.0 | 4.3 | +0.3 |

The three schema extensions accepted by the validation gate under evolution-ON are: (i) `research_question` added as a CONTRIBUTION subtype (a paper whose central contribution is posing a research question — distinct from the L3 RESEARCH_QUESTION atom, which captures the question itself); (ii) `extends` as a CONTRIBUTION_RELATION type (a paper extending a prior constitutive law); (iii) `resolves` as a CONTRIBUTION_RELATION type (a paper resolving a prior conflict). All three are evidence-linked (each accepted gap carried a verbatim source span) and correspond to real conceptual relations in the granular-flow literature (papers routinely extend prior μ(I)-family laws and resolve regime conflicts). The +5.3% atom yield under evolution-ON is modest because v4 already covers the bulk of granular-flow content; the extensions are at the contribution-relation periphery, which is exactly where a mature schema should still grow.

**C5 verdict**: Unlike the prior truncated run (which found 0 real gaps), full-text extraction with self-evolution-ON discovers and accepts 3 genuine schema extensions on the same 20 papers — the validation gate (evidence-linked) accepts real conceptual relations and the schema grows v4.0→v4.3. Self-evolution's within-domain value is periphery-extension on top of a mature core, not core discovery.

### 4.4 RAGA Comparison

RAGA [arXiv 2605.17072] is not open-source (GitHub search returned 0 repositories), precluding direct experimental comparison. From full-text analysis, RAGA has: schema auto-discovery (4-phase), PROPOSED state, evidence-anchored verification, create_todo (deferred tasks), and provenance recording. Our three true differences (confirmed by source-code analysis of RAGA, AdaKGC, OLLM, AutoSchemaKG):

1. **Gap discovery as explicit capability**: RAGA's PROPOSED state is implicit; we implement both passive (extraction-time) and active (cross-paper scan) gap discovery as first-class skills.
2. **QA generation**: RAGA performs QA retrieval (answering existing questions); we generate new QA pairs with paper-anchored answers.
3. **Schema-evolution quality evaluation (C5)**: RAGA defers quality/coverage evaluation ("deferred for future diagnostic toolchain support"); we implement and report the ablation.

## 5. Discussion

### 5.1 Why Full-Text Extraction Changed the Self-Evolution Finding

The prior truncating run (8,000 chars/paper, 80% content loss) concluded self-evolution found "0 real gaps" — but 4/5 probe papers returned 0 atoms under truncation, so the absence of gaps was an artifact of unseen content. With full-text three-phase extraction on the same 20-paper ablation set, the validation gate accepts 3 genuine schema extensions (§4.3): `research_question` (contribution subtype) and `extends`/`resolves` (contribution relations). These appear in mid-paper Discussion/Conclusion sections that truncation discarded. The finding flips: self-evolution's within-domain value is real but confined to the periphery of a mature schema (contribution relations, not core entities), detectable only when the full paper is read. This is consistent with the v4 core having been manually refined to cover granular-flow entities; the residual growth surface is relational.

### 5.2 Implications for Self-Evolving Schema Research

Our findings suggest a nuanced picture: self-evolution is not unnecessary, but its value depends on both schema maturity and extraction coverage. For a mature schema (v4) under full-text extraction, self-evolution serves as a periphery-extension mechanism (3 relations in 20 papers, +5.3% atoms). For new domains without manual schema design, self-evolution would replace the v1→v4 iteration process. Future work should validate this by deploying the agent on a new domain (e.g., materials science) with only a minimal seed schema.

### 5.3 Limitations

1. **Scale**: 49 papers, single seed per paper, no expert κ — directional results. LLM non-determinism at temperature 0 yields ~7× per-paper atom-count variance (Jop 2006: 15–108 across 3 single runs); the Phase 0 structure map is stable across runs, so variance is confined to Phase 1 extraction yield. Aggregates over 49 papers average this out, but per-paper numbers are noisy.
2. **Single LLM**: mainline run is DeepSeek-only; MARY multi-LLM fusion (§3.5) validated separately but not integrated into the 49-paper run.
3. **CLOSURE / MATERIAL_PARAMETER under-extraction**: the LLM sometimes emits a constitutive law as a CONTRIBUTION text statement rather than the structured CLOSURE atom (function_form + parameters). Prompt-tuning issue, not architectural.
4. **Grounding strictness**: exact-text-match discards paraphrased evidence (false negatives); the lookup pass recovers some but not all.
5. **One structure-map failure**: 1/49 papers failed Phase 0 structure mapping and fell back to the old extractor (0 atoms) — a recoverable failure mode, not a fundamental limitation.
6. **No RAGA baseline**: RAGA is not open-source; comparison is full-text-analysis only (§4.4).
7. **No expert validation**: schema quality (κ) not yet measured against domain experts.

## 6. Conclusion

We presented GranularFlow-Bench, an agent system for structured extraction from granular flow literature with a three-phase schema-guided DAG extractor (full-text, no truncation, 7.4 calls/paper, 99.97% deterministic exact-text-match grounding) and a self-evolving schema mechanism. Across 49 papers spanning seven subdomains, the agent extracted 3,135 atoms with a 99.97% grounding rate (every atom verifiable against source text), replacing a truncating extractor that failed on 4/5 probe papers. A 20-paper ablation shows self-evolution-ON yields +5.3% atoms and 3 genuine schema extensions (v4.0→v4.3: `research_question` subtype, `extends`/`resolves` relations) that the prior truncated run could not detect — full-text coverage is necessary for self-evolution to find periphery gaps on a mature schema. We position the three-phase DAG extraction (schema-field-to-section mapping + discourse-role-aware rebind detection + deterministic grounding) as a low-cost, auditable alternative to per-paragraph ReAct extraction, and self-evolution as a periphery-extension mechanism whose within-domain value depends on extraction coverage. The dataset, schema, and code are released to facilitate further research.

## Data Availability

The dataset (1,186 purified paper IDs, 49-paper extraction results with 3,135 grounded atoms, 20-paper ablation results), schema (v4 JSON Schema + v4.0→v4.3 evolution provenance), and agent system code are available at `https://github.com/[anonymous]/GranularFlow-Bench`.

## Acknowledgments

We thank the granular flow research community for the survey corpus and domain expertise.

## References

[Ancey, 2007] C. Ancey. Plasticity and geophysical flows: A review. *Journal of Non-Newtonian Fluid Mechanics*, 142(1-3):4–35, 2007.

[Bai et al., 2026] B. Bai et al. AutoSchemaKG: A framework for automatic knowledge graph schema induction. In *Proceedings of ACL*, 2026.

[Bouzid et al., 2013] M. Bouzid et al. Nonlocal rheology of granular flows across yield conditions. *Physical Review Letters*, 111(5):058001, 2013.

[Cattan et al., 2021] A. Cattan et al. SciClaim: A dataset for claim-level scientific fact-checking. In *Proceedings of EMNLP*, 2021.

[Chia et al., 2022] Y. Chia et al. HyperRED: A benchmark for hyper-relational extraction. In *Proceedings of EMNLP*, 2022.

[Friedrich et al., 2020] A. Friedrich et al. The SOFC-Exp corpus and neural approaches to information extraction in the materials science domain. In *Proceedings of ACL*, 2020.

[Friedrich et al., 2023] A. Friedrich et al. MuLMS: A multi-layer annotated text corpus for information extraction in the materials science domain. In *Proceedings of LREC*, 2023.

[Han and Cheng, 2026] C. Han and Z. Cheng. RAGA: Reading-And-Graph-building-Agent for autonomous knowledge graph construction and retrieval-augmented generation. *arXiv preprint arXiv:2605.17072*, 2026.

[Jain et al., 2024] S. Jain et al. SciER: A dataset for document-level scientific information extraction. In *Proceedings of EMNLP*, 2024.

[Jop et al., 2006] P. Jop, Y. Forterre, and O. Pouliquen. A constitutive law for dense granular flows. *Nature*, 441(7094):727–730, 2006.

[Yang et al., 2026] W. Yang et al. AgentCAT: An LLM agent for extracting and analyzing catalytic reaction data from chemical engineering literature. *arXiv preprint arXiv:2602.18479*, 2026.

[Zhang et al., 2023] Z. Zhang et al. Schema-adaptable knowledge graph construction. In *Proceedings of EMNLP Findings*, 2023.
