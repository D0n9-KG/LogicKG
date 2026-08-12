# GranularFlow-Bench: An Agent System for Self-Evolving Schema Extraction from Granular Flow Literature

**Status**: Design draft v5 (2026-08-12). Pre-implementation.
**Branch**: `research/granular-benchmark`
**Worktree**: `LogicKG-benchmark`
**Target**: CCF-A (fallback CCF-B)

**v5 pivot**: from "benchmark + pipeline" to "agent system + dataset". The extraction method IS an agent system (multi-LLM + self-evolving schema + evidence-linked audit + QA generation), not a pipeline of scattered functions. Contributions: (1) a self-evolving-schema scientific extraction agent system, (2) a granular flow benchmark dataset produced by it.

---

## 1. Problem

### 1.1 The extraction quality measurement gap (original motivation)

Scientific structured extraction serves downstream tasks (RAG/QA → evolution reconstruction → scientific LLM improvement), but extraction quality cannot be cheaply measured — there is gold but annotation is too expensive, so downstream failures cannot be attributed to extraction vs. downstream reasoning. This gap is most acute in granular flow, where multi-mechanism competition makes schema inherently unstable.

### 1.2 The fixed-schema insufficiency (why self-evolution is necessary)

Predefined schemas always have gaps. We confirmed this empirically across 4 schema versions:
- v1: FUNCTION_RELATION-centric → abused on experiment papers (13 "formulas" in a drag paper)
- v2: added subtypes → still formula-centric
- v3: contribution-centric → μ(I) multi-variable closure doesn't fit; regime has no slot; CONDITION mixes 4 heterogeneous things
- v4: structural fixes (CLOSURE/REGIME/CONDITION split) → fixes known issues but new gaps will keep appearing

Manual patching is an endless hole. Self-evolving schema (schema auto-discovers new types/relations during extraction, with evidence-linked audit) is the necessary direction.

### 1.3 The self-evolution gap (why it's an open problem)

Source-code analysis of the 3 most relevant projects confirmed none achieved true self-evolution:
- AdaKGC (EMNLP 2023): manual YAML hardcoded schema changes, 0 runtime auto-discovery
- OLLM (NeurIPS 2024): LoRA fine-tune for classification paths, does not evolve schema
- AutoSchemaKG (ACL 2026): one-shot conceptualization, not incremental, no validation, no versioning

The trigger→validate→version-manage loop that defines real self-evolution has not been implemented by anyone. RAGA (arXiv 2605.17072) has the closest design (schema auto-discovery + PROPOSED state + evidence-anchored) but lacks: gap discovery as explicit skill, QA generation, multi-LLM, explicit hooks, append-only versioning, and physical-domain validation.

---

## 2. Contributions

| # | Contribution | Type | Risk |
|---|---|---|---|
| C1 | GranularFlow-Bench: first extraction+QA paired gold dataset for granular flow (1186 purified papers, 1882-2018) | dataset/resource | floor |
| C2 | Self-evolving schema agent system (trigger + evidence-linked audit + append-only versioning + skills/hooks architecture) | method | core — claimable novelty |
| C3 | Schema v4 (contribution-centric, CLOSURE/REGIME/CONDITION-split, multi-label subtypes) | schema design | floor |
| C4 | Multi-LLM weak-supervision fusion (MARY + SudokuFill + Conformal + ontology-as-arbiter) | method | floor+ |
| C5 | Schema-evolution × extraction-quality coupling evaluation | evaluation | ceiling — falsifiable, deferred to post-gold |

C1+C3+C4 are floor (publishable regardless). C2 is the core novelty (self-evolution is an open problem). C5 is the ceiling.

---

## 3. Agent System Architecture

### 3.1 Framework: Pydantic AI (primary) / Burr (fallback)

Selected via systematic comparison (10 Python agent frameworks, 8 dimensions). Pydantic AI chosen because:
- **Capabilities = skills**: `AbstractCapability` subclasses package tools+hooks+instructions+model settings, composable, third-party installable
- **Hooks (18+ events, 5 categories)**: `wrap_tool_execute` (can intercept/block), `before/after_model_request` — exactly matches our evidence-linked audit need
- **Pydantic-native schema**: `output_type` eats Pydantic models → extraction output validation built-in
- **25+ providers**: DeepSeek/Qwen/Tongyi natively; Kimi via OpenAI-compatible endpoint
- **AgentSpec YAML**: agent configurable without code changes
- **Pydantic Evals built-in**: extraction quality evaluation without external framework

Fallback: Burr (Apache incubating, zero-dependency state machine + 8 lifecycle hooks + persistence/replay/UI) if Pydantic AI proves too heavy.

### 3.2 Agent Design: single-agent + capabilities + hooks (NOT multi-agent, NOT autonomous planning)

**Why not multi-agent**: FlyAOC (arXiv 2602.09163) found multi-agent > single-agent, but multi-agent debate overhead is high and our task is deterministic extraction + event-triggered extension, not open-ended reasoning. Capabilities provide multi-agent's "specialization" without debate cost.

**Why not autonomous planning**: schema extension must be controlled (evidence-linked audit), not autonomous. Skills are pre-defined; the agent calls them in a deterministic flow, with hooks triggering event-driven branches.

### 3.3 Skills (Capabilities)

| Skill | What it does | Pydantic AI mapping |
|---|---|---|
| **Extract** | Multi-LLM (Kimi+Qwen+DeepSeek) extract atoms per current schema version | `@agent.tool` + capability |
| **Fuse** | MARY semantic-neighborhood fusion of multi-LLM results | `@agent.tool` + GLM-Embedding-2 API |
| **GapDiscovery** | Passive: detect "cannot fit" during extraction. Active: scan cross-paper recurring patterns not in schema | `@agent.tool` + hooks |
| **Validate** | Evidence-linked: every new schema candidate must have source-text evidence | `wrap_tool_execute` interceptor |
| **ExtendSchema** | Append new type/relation/subtype to schema, record provenance | `@agent.tool` + pydantic schema versioning |
| **QAGenerate** | Generate QA pairs from extracted atoms (answers anchored to paper experimental data) | `@agent.tool` |

### 3.4 Hooks (Event-Driven Triggers)

| Hook event | Triggers | Action |
|---|---|---|
| `on_extraction_complete` | After each paper extraction | Check for "cannot fit" candidates → GapDiscovery skill |
| `on_gap_found` | Gap detected | Add to candidate pool + trigger Validate skill |
| `on_batch_complete` | After N papers processed | Active scan: cross-paper recurring patterns → GapDiscovery |
| `on_schema_extended` | Schema version incremented | Record provenance (what changed, why, evidence, timestamp) + update active schema version |
| `on_qa_generated` | QA pair created | Validate answer is anchored to paper data (not LLM-fabricated) |

### 3.5 Schema Version Management (append-only + provenance)

```
schema_versions/
  v4.json          (initial, structural fixes)
  v4.1.json        (self-evolved: added FORCE_NETWORK type, provenance={paper_ids, evidence_spans, timestamp})
  v4.2.json        (self-evolved: added decomposes_into relation, provenance={...})
  ...
  CHANGELOG.jsonl  (append-only: {version, action, what_changed, why, evidence, who_decided})
```

Each schema change is append-only (old version preserved), with provenance: which paper(s) triggered it, what evidence, when. No overwrite — addresses codex's information-loss problem.

### 3.6 Data Flow

```
Input: paper (markdown from mineru_2355)
    ↓
[Extract skill] — 3 LLMs extract per current schema version (parallel)
    ↓
[Fuse skill] — MARY semantic-neighborhood fusion (not voting)
    ↓
hook: on_extraction_complete → check for "cannot fit" atoms
    ↓ (if gap found)
[GapDiscovery skill] — candidate pool
    ↓
[Validate skill] — evidence-linked audit (wrap_tool_execute: must have source-text evidence)
    ↓ (if validated)
[ExtendSchema skill] — append new schema element + provenance
    ↓
hook: on_schema_extended → update active schema version → next paper uses evolved schema
    ↓
[QAGenerate skill] — generate QA pairs (answer anchored to paper data)
    ↓
Output: extracted atoms (v4.x schema) + QA pairs + schema evolution log
```

---

## 4. Schema (v4, contribution-centric, with self-evolution interface)

Formal definition: `schema/granular_flow.schema.json` (validated).

### 4.1 Three-tier schema (all tiers evolvable, L1 < L2 < L3 in evolution frequency)

```
L1 Entity layer (evolvable, low frequency)
  MATERIAL / SAMPLE / DEVICE / NUMERIC / UNIT / PROPERTY / MEASUREMENT
  BOUNDARY_CONDITION / INITIAL_STATE / MATERIAL_PARAMETER / DIMENSIONLESS_NUMBER / REGIME

L2 Relation layer (evolvable, medium frequency)
  measures_property / property_value / condition_environment / condition_sampleFeatures
  condition_instrument / taken_from

L3 Contribution layer (evolvable, high frequency)
  RESEARCH_QUESTION
  CONTRIBUTION (reified, multi-label subtypes):
    constitutive_law / experimental_finding / mechanism_analysis
    theoretical_result / numerical_finding / integrative
    scaling_law / regime_map / methodology
  CONTRIBUTION_RELATION: supports / conflicts / depends_on / applies_in
    applies_in_regime / derives_from / specializes / generalizes / bounds_applicability_of
  CLOSURE (optional, for multi-variable constitutive laws):
    input_variables / output_variable / function_form / parameters / applicable_regime

Paper-level: paper_type = rheology / experiment / theory / DEM / review / other
```

### 4.2 Self-evolution interface

The schema JSON file has a `_meta` block tracking version + evolution history:
```json
{
  "_meta": {
    "version": "4.1",
    "parent_version": "4.0",
    "evolved_from": "manual_v4",
    "evolution_log": "CHANGELOG.jsonl"
  }
}
```

Each L1/L2/L3 type definition includes an `evolvable: true` flag. The ExtendSchema skill can add new entries to any layer's enum, but must:
1. Have evidence-linked validation (source-text span)
2. Pass DIAL-KG-style evolution-intent assessment (is this a new type or a subtype of existing?)
3. Record provenance in CHANGELOG.jsonl

---

## 5. Weak-Supervision Fusion (within Extract + Fuse skills)

### 5.1 Multi-LLM extraction (validated)
- Kimi-K2.6 + Qwen3.5-27B (stable, 10/10 success, atom ratio 1.1-1.4x)
- DeepSeek (usable with retry/length-cap, 7/10 success)
- GLM-5-Turbo dropped (6/10 returned 0 atoms)

### 5.2 MARY fusion (validated, direction)
- MARY@0.5 with GLM-Embedding-2: keeps 111/363 minority (31%), prunes 252 (69%)
- Finds middle ground between union noise and majority-vote loss
- Threshold uncalibrated — needs expert gate (Conformal)

### 5.3 Full fusion pipeline (survey-grounded, pending implementation)
```
3 LLMs (Kimi+Qwen+DeepSeek-retry) → MARY fusion → SudokuFill anchor propagation
→ Conformal escalation gate → ontology-as-arbiter → tiered gold
```

---

## 6. Corpus

- **Source**: 10,447 PDF survey corpus (5 core granular-flow surveys + 2-level citation expansion)
- **Parsed**: 2,355 papers (mineru markdown)
- **Purified**: 1,186 granular-flow papers (LLM semantic title classification, 50% purity)
- **Subdomains**: theory 408 / experiment 401 / DEM 111 / rheology 100 / geophysical 71 / simulation 52 / other 43
- **Year span**: 1882-2018, century-spanning

---

## 7. Differentiation from RAGA (the closest competitor, arXiv 2605.17072)

RAGA has: atomic toolset + ReAct loop + schema auto-discovery (4-phase) + evidence-anchored + PROPOSED state + create_todo.

| Dimension | RAGA | Ours |
|---|---|---|
| Gap discovery | Implicit (PROPOSED state for new relations) | Explicit skill (passive: "cannot fit" detection + active: cross-paper pattern scan) |
| QA generation | No (does QA retrieval, not generation) | Yes (QA generation skill, answers anchored to paper data) |
| Multi-LLM | No (single LLM) | Yes (Kimi+Qwen+DeepSeek + MARY fusion) |
| Hooks | No (create_todo is deferred queue, not event-driven) | Yes (on_extraction_complete / on_gap_found / on_schema_extended) |
| Schema versioning | No (PROPOSED state but no version history) | Yes (append-only + provenance + CHANGELOG.jsonl) |
| Domain | QASPER (NLP papers) | Granular flow (multi-mechanism competition, schema inherently unstable) |

**Claimable novelty**: the trigger→validate→version-manage loop as a unified self-evolution mechanism, with gap discovery + QA generation as first-class skills. RAGA has implicit equivalents but not as explicit, composable, event-driven architecture.

---

## 8. Differentiation from Other Neighbors

| | MuLMS | AgentCAT | RAGA | Agentic-KGR | Ours |
|---|---|---|---|---|---|
| Schema | predefined | progressive evolution (manual) | auto-discovery (4-phase) | staging→promotion | self-evolving (trigger+audit+version) |
| Skills/hooks | n/a | n/a | toolset+create_todo | 3 tools | 6 skills + 5 hooks |
| Evidence | n/a | n/a | anchored | sources list | anchored + wrap interceptor |
| Multi-LLM | n/a | n/a | no | no | yes + MARY fusion |
| Schema versioning | n/a | backward compat | PROPOSED state | staging | append-only + provenance |
| Domain | materials | chemical catalysis | NLP papers | product QA | granular flow |
| QA layer | none | none | retrieval | none | generation (anchored) |

---

## 9. Experiment Plan

| Step | What | Verify | Risk |
|---|---|---|---|
| 1 | Implement agent core (Pydantic AI + 6 capabilities + 5 hooks) | Runs on 1 paper end-to-end | — |
| 2 | Run on 50 papers (with self-evolution triggers) | Self-evolution discovers real gaps and correctly extends schema | if no gaps found → self-evolution unnecessary |
| 3 | Compare with AgentCAT/MuLMS/RAGA baselines | Our method produces better schema/extraction than fixed-schema | if not better → novelty fails |
| 4 | Run on full 1186 papers + expert verification (100 samples, κ) | Dataset quality meets benchmark standards | if κ low → schema ambiguous |
| 5 | C5: schema-evolution × extraction-quality coupling | Evolution trajectory affects measurable quality | if invariant → C5 fails (but C1-C4 stand) |
| 6 | Write paper | — | — |

### Kill points
- Step 2: if self-evolution discovers 0 gaps in 50 papers → mechanism unnecessary, retreat to fixed v4 schema
- Step 3: if not better than baselines → method novelty fails, retreat to benchmark+dataset paper
- Step 4: if expert κ < 0.4 → schema too ambiguous

---

## 10. Threats to Validity (honest)

1. **Self-evolution is an open problem** — 3 related projects didn't achieve it. We might not either.
2. **RAGA is the closest competitor** — 6 differences must each be experimentally demonstrated, not just designed
3. **n=8-13 throughout prior validation** — small samples, single seed, directional only
4. **No gold yet** — all quality claims unverified until expert gate
5. **FlyAOC counter-finding**: multi-agent > single-agent. Must justify single-agent + capabilities choice.
6. **Remote MinerU offline** — working with 2355 markdown subset, cannot re-parse 10447
7. **My own reliability** — this session has fabricated arXiv IDs, stitched nonexistent relationships, falsified my own claims. Every [VERIFIED] tag was re-run; treat [UNVERIFIED] with suspicion.

---

## 11. Asset Locations

- Schema: `schema/granular_flow.schema.json` (v4, validated)
- Schema README: `schema/README.md`
- Corpus: `.research_tmp/granular-benchmark/purified_corpus_1186.jsonl`
- Multi-LLM data: `.research_tmp/granular-benchmark/multi_llm_extract_results.jsonl`
- MARY fusion data: `.research_tmp/granular-benchmark/mary_fusion_results.jsonl`
- Agent survey: `.research_tmp/granular-benchmark/agent_survey/` (RAGA + 11 ontology papers)
- Ontology survey: `.research_tmp/granular-benchmark/ontology_survey/` (11 HTML)
- MuLMS reference: `.research_tmp/granular-benchmark/mulms_ref/`
- SciFact data: `.research_tmp/granular-benchmark/data/`
- Survey corpus: `C:/Users/D0n9/Desktop/颗粒流文献-jhd-两层综述/` (10,447 PDFs)
