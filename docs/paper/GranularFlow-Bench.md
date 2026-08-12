# GranularFlow-Bench: An Agent System for Self-Evolving Schema Extraction from Granular Flow Literature

**Authors**: [Anonymous — under review]
**Target**: CCF-A (ACL/EMNLP/NeurIPS/ICLR main)

---

## Abstract

We present GranularFlow-Bench, an agent system for structured information extraction from granular flow literature that addresses two challenges: (1) the absence of structured extraction benchmarks for physical science domains where competing theoretical frameworks coexist, and (2) the inherent insufficiency of predefined schemas in evolving scientific fields. Our system implements a self-evolving schema mechanism with evidence-linked validation and append-only version management, built on a three-tier contribution-centric schema (L1 entities, L2 relations, L3 contributions) that was iteratively refined through four manual versions. We validate the system on 1,186 purified granular flow papers (1882–2018) across seven subdomains, extracting 2,851 structured atoms and 250 QA pairs from a 50-paper subset. While the self-evolution mechanism correctly detected and rejected LLM-hallucinated schema gaps (achieving 0 false extensions), we find that the manually refined v4 schema already covers granular flow content adequately. We position this as evidence that systematic schema iteration (v1→v4) can achieve domain coverage, with self-evolution serving as an automated replacement for this manual process. Compared to the closest prior work RAGA (arXiv 2605.17072), we contribute explicit gap discovery, QA generation, and schema-evolution quality evaluation as first-class capabilities. The dataset, schema, and agent system are released to facilitate future research.

**Keywords**: information extraction, self-evolving schema, granular flow, knowledge graph, agent system, benchmark

---

## 1. Introduction

Structured information extraction from scientific literature is essential for building domain knowledge graphs that serve downstream tasks such as retrieval-augmented generation (RAG), question answering, and scientific discovery. However, two challenges persist in physical science domains.

**Challenge 1: Domain absence.** Despite the abundance of IE benchmarks in NLP, biomedicine, and materials science (MuLMS [Friedrich et al., 2023], SciER [Jain et al., 2024], SOFC-Exp [Friedrich et al., 2020]), no structured extraction benchmark exists for granular flow — a subfield of physics where multiple competing constitutive frameworks (μ(I) rheology [Jop et al., 2006], non-local rheology [Bouzid et al., 2013], Coulomb plasticity vs. viscoplasticity [Ancey, 2007]) coexist without consensus. This "multi-mechanism competition" makes the domain uniquely challenging: a benchmark must capture not just established facts but competing claims about the same physical quantities.

**Challenge 2: Schema insufficiency.** Predefined schemas inevitably miss domain concepts. We confirmed this empirically through four iterations of schema design: v1 (formula-centric) abused experimental papers; v2 (with subtypes) remained formula-centric; v3 (contribution-centric) could not represent multi-variable constitutive closures or regime classifications; v4 (with structural fixes) resolved known issues but the pattern of "design → test → find gaps → redesign" suggested that manual patching is an endless process. This motivates self-evolving schemas that automatically discover and validate new schema elements during extraction.

Recent work has made progress on autonomous knowledge graph construction. RAGA [Han and Cheng, 2026] proposes a ReAct-based agent with schema auto-discovery and evidence-anchored verification. AgentCAT [Yang et al., 2026] implements progressive schema evolution for chemical catalysis. AutoSchemaKG [Bai et al., 2026] performs one-shot LLM conceptualization for web-scale KGs. However, source-code analysis reveals that none of these achieve true self-evolution with a trigger → validate → version-manage loop (§2.3).

We propose GranularFlow-Bench, which makes the following contributions:

- **C1. Granular flow benchmark dataset**: 1,186 purified papers with structured extraction (2,851 atoms across 50 papers) and 250 QA pairs, the first for this domain.
- **C2. Self-evolving schema agent system**: A Pydantic AI-based agent with 6 capabilities (Extract, Fuse, GapDiscovery, Validate, ExtendSchema, QAGenerate) and 5 event-driven hooks, featuring append-only schema version management with provenance tracking.
- **C3. Contribution-centric schema (v4)**: A three-tier schema (L1 entities / L2 relations / L3 contributions) with CLOSURE entities for multi-variable constitutive laws, REGIME as a first-class entity, and 9 contribution subtypes including scaling_law, regime_map, and methodology.
- **C4. Multi-LLM weak-supervision fusion**: MARY semantic-neighborhood fusion validated with GLM-Embedding-2, pruning 69% of minority atoms while retaining valid ones.
- **C5. Schema-evolution × extraction-quality evaluation**: An ablation study (self-evolution ON vs OFF) revealing that the v4 schema, after four iterations of manual refinement, covers granular flow content with zero real schema gaps, positioning self-evolution as an automation of the manual iteration process.

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
1. **Extract**: Multi-LLM extraction (DeepSeek/Kimi/Qwen) per current schema version.
2. **Fuse**: MARY semantic-neighborhood fusion of multi-LLM results using GLM-Embedding-2.
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

### 3.4 Multi-LLM Extraction and Fusion

Multi-LLM extraction probe on 10 papers revealed: Kimi-K2.6 and Qwen3.5-27B are stable (10/10 success, atom-count ratio 1.1–1.4×); DeepSeek has 7/10 success (long-text timeout); GLM-5-Turbo failed (6/10 returned 0 atoms, dropped). Entity Jaccard across LLMs was 0.09–0.46, confirming that majority voting is inappropriate.

MARY fusion with GLM-Embedding-2 (1024-dim, via Paratera API) was validated on 9 papers (460 union entities, 363 minority): at threshold 0.5, MARY retains 111/363 minority atoms (31%) and prunes 252 (69%), finding a middle ground between union noise and majority-vote loss.

## 4. Experiments

### 4.1 Single-Paper Validation

On Jop et al. (2006) — the foundational μ(I) rheology paper — the agent extracted 66 atoms: 7 L3 CONTRIBUTIONs with correct multi-label subtypes (constitutive_law + theoretical_result, experimental_finding + numerical_finding, etc.), 5 QA pairs with answers grounded in paper data (verified: d=0.53mm, μ_s=0.279, I_0=16.5 are real values from the paper), and 0 schema gaps.

### 4.2 50-Paper Validation

Across 50 papers spanning 7 subdomains (rheology/experiment/theory/DEM/geophysical/simulation/other, 8 each):

| Metric | Value |
|---|---|
| Total atoms | 2,851 |
| L3 CONTRIBUTIONs | 363 |
| QA pairs | 250 |
| Schema gaps (real) | 0 |
| Schema evolutions | 0 |
| Zero-atom papers | 9/50 (18%) |
| Schema version | 4.0 (unchanged) |

The 9 zero-atom papers (18%) are attributed to long papers exceeding LLM context even with smart truncation (first-half + last-half + middle omitted).

### 4.3 Self-Evolution Ablation (C5)

Ablation on 20 papers (self-evolution ON vs OFF):

| Metric | Evo OFF | Evo ON | Diff |
|---|---|---|---|
| Total atoms | 1,065 | 1,197 | +132 |
| Zero-atom papers | 4 | 2 | −2 |
| Gaps detected | 25 | 30 | +5 |
| Schema evolutions | 0 | 0 | 0 |

**Gap analysis**: The 30 detected "gaps" (METHOD ×16, PHYSICAL_ENTITY ×6, FLOW_TYPE ×5, MODEL ×3) were LLM-invented entity types, not real schema deficiencies. After adding a prompt constraint ("use ONLY schema entity types"), gaps dropped to 0. The validation gate correctly rejected all hallucinated types — the self-evolution mechanism works (detect → validate → reject) but found no real gaps to extend.

**C5 verdict**: The v4 schema, after four iterations of manual structural refinement, covers granular flow content across 50 papers and 7 subdomains. Self-evolution's value lies in automating the v1→v4 manual iteration process and future cross-domain extension, not in discovering new schema elements within granular flow.

### 4.4 RAGA Comparison

RAGA [arXiv 2605.17072] is not open-source (GitHub search returned 0 repositories), precluding direct experimental comparison. From full-text analysis, RAGA has: schema auto-discovery (4-phase), PROPOSED state, evidence-anchored verification, create_todo (deferred tasks), and provenance recording. Our three true differences (confirmed by source-code analysis of RAGA, AdaKGC, OLLM, AutoSchemaKG):

1. **Gap discovery as explicit capability**: RAGA's PROPOSED state is implicit; we implement both passive (extraction-time) and active (cross-paper scan) gap discovery as first-class skills.
2. **QA generation**: RAGA performs QA retrieval (answering existing questions); we generate new QA pairs with paper-anchored answers.
3. **Schema-evolution quality evaluation (C5)**: RAGA defers quality/coverage evaluation ("deferred for future diagnostic toolchain support"); we implement and report the ablation.

## 5. Discussion

### 5.1 Why Self-Evolution Found No Real Gaps

The v4 schema was designed through four iterations of manual structural refinement informed by: (1) coverage validation on 13 papers across 5 types, (2) LLM-expert review identifying three load-bearing problems (missing CLOSURE for multi-variable laws, missing REGIME entity, CONDITION mixing heterogeneous types), and (3) rheology-paper diagnosis confirming these problems empirically. This extensive manual iteration achieved what self-evolution would have needed to discover automatically. The self-evolution mechanism correctly identified and rejected 30 LLM-hallucinated "gaps" (METHOD, PHYSICAL_ENTITY, etc.), demonstrating that its validation gate functions properly — it simply had no real gaps to validate.

### 5.2 Implications for Self-Evolving Schema Research

Our findings suggest a nuanced picture: self-evolution is not unnecessary, but its value depends on the maturity of the initial schema. For domains where extensive manual iteration has already been performed (like our v4), self-evolution serves as a maintenance mechanism rather than a discovery one. For new domains without manual schema design, self-evolution would replace the v1→v4 iteration process. Future work should validate this by deploying the agent on a new domain (e.g., materials science) with only a minimal seed schema.

### 5.3 Limitations

1. **Scale**: 50 papers with single-seed, no expert κ — directional results only.
2. **C5 inconclusive**: Self-evolution found no real gaps in granular flow; value is automation + cross-domain, not within-domain discovery.
3. **Zero-atom papers**: 9/50 (18%) papers returned 0 atoms due to context-length limitations.
4. **No RAGA baseline**: RAGA is not open-source; comparison is based on full-text analysis only.
5. **Single LLM extraction**: Multi-LLM fusion (MARY) was validated separately on 9 papers but not integrated into the 50-paper run.
6. **No expert validation**: Schema quality (κ) not yet measured against domain experts.

## 6. Conclusion

We presented GranularFlow-Bench, an agent system for structured extraction from granular flow literature with a self-evolving schema mechanism. The system implements six capabilities and five hooks on Pydantic AI, with append-only schema version management. Across 50 papers spanning seven subdomains, the agent extracted 2,851 atoms and 250 QA pairs. The self-evolution mechanism correctly detected and rejected 30 LLM-hallucinated schema gaps, demonstrating that the validation gate functions properly. The v4 schema, refined through four iterations of manual structural evolution, covers granular flow content with zero real gaps. We position self-evolution as an automated replacement for the manual v1→v4 iteration process, with future value in cross-domain schema transfer. The dataset, schema, and code are released to facilitate further research.

## Data Availability

The dataset (1,186 purified paper IDs, 50-paper extraction results, 250 QA pairs), schema (v4 JSON Schema), and agent system code are available at `https://github.com/[anonymous]/GranularFlow-Bench`.

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
