# Self-Evolution v2: Intra-DAG, Discourse-Weighted, Evidence-Anchored

**Status**: Design (2026-08-13). Pre-implementation.
**Supersedes**: the post-hoc self-evolution pass in `gap_discovery.py` + `agent.py` (which runs gap detection AFTER extraction completes).

## 1. Problem

The current self-evolution is a **separate pass after extraction**:
```
Phase 0-2 extract → _detect_gaps on grounded atoms → validate_gap → extend_schema
```
This is structurally the same as the frontier (EDC's post-hoc canonicalize; AutoSchemaKG's pre-extract one-shot). Two consequences:
1. **No differentiation from EDC / AutoSchemaKG / DIAL-KG** — all are two-stage (schema-before or schema-after), none evolve schema *during* extraction.
2. **Wastes the DAG topology** — our three-phase DAG gives a structural signal (which section/discourse-role a gap appears in, and whether it recurs across DAG nodes *within one paper*) that a post-hoc flat scan cannot use.

The P0 bug fixes (validator now evidence-anchored + domain-agnostic; QA now verbatim-grounded) repaired correctness but did NOT change the architecture. This doc proposes the architectural upgrade.

## 2. Frontier positioning (the differentiator table)

| Dimension | EDC (2404.03868) | AutoSchemaKG (2505.23628) | DIAL-KG | **Ours (proposed)** |
|---|---|---|---|---|
| Evolution timing | post-hoc | pre-extract (one-shot) | dialog/LLM | **intra-extraction (mid-DAG)** |
| Trigger | all triples, post-hoc | LLM conceptualization | conversation | **grounded atom enum-miss at node exit** |
| Validation evidence | triple match | none (LLM output = schema) | LLM | **verbatim source span from triggering atom** |
| Recurrence signal | cross-paper | none | none | **intra-paper cross-node + cross-paper** |
| Discourse role | none | none | none | **definition-role weighted** |
| Downstream benefit | next extraction round | same extraction | same extraction | **same DAG pass: later nodes use extended schema** |

**Structural vacancy**: "schema evolves *during* extraction, with downstream extraction nodes benefiting in the same pass" — no frontier work occupies this position. EDC is explicitly post-hoc; AutoSchemaKG explicitly pre-extract. This is inferable from their architecture; a focused literature check (arXiv search "intra-extraction schema evolution" / "during-extraction schema update") is a TODO before paper submission.

## 3. Mechanism

### 3.1 Per-node gap detection (replaces post-hoc _detect_gaps)

At the end of each Phase 1 DAG node (after the node's atoms are extracted + grounded), run `_detect_gaps` on THAT node's atoms only. Gaps are tagged with:
- `node_id` (which DAG node)
- `section` + `discourse_role` (from the Phase 0 structure map)
- `evidence_span` (the triggering atom's verbatim span, already grounded)

### 3.2 Intra-paper cross-node recurrence

A gap candidate is scored by how many DAG nodes it appears in *within the same paper*:
- appears in 1 node → low confidence (instance noise)
- appears in ≥2 nodes (e.g. Method + Results + Discussion) → high confidence (a cross-section concept, likely a real schema slot)

This is a **stronger and earlier** signal than EDC's cross-paper recurrence (which needs ≥3 papers). One paper's DAG topology is enough.

### 3.3 Discourse-role weighting

Weight gap confidence by the discourse role of the node it appeared in:
- `definition` (Method) → weight 1.5 (definitional sections introduce the terms that *should* be schema slots)
- `summary`/`claim` (Abstract/Conclusion) → weight 1.2 (headline concepts)
- `observation` (Results) → weight 0.7 (instance-specific values, likely noise)
- `interpretation` (Discussion) → weight 1.0

No frontier work uses discourse roles for schema-evolution gating (verified vacant in ACL index, memory `acl-index-and-representational-limits-position`).

### 3.4 Evidence-anchored validation (already implemented in P0)

`validate_gap` receives the triggering atom's verbatim `evidence_span` and the current schema, judges whether the span denotes a distinct new category. Domain-agnostic. (P0 bug fix.)

### 3.5 Forward propagation (the core novelty)

When a gap is accepted at node N_k, the schema extends (vX → vX+1). The downstream nodes N_{k+1..} (topologically after N_k) **re-fetch `schema_manager.get_schema_prompt()` before their extraction call** — so they extract with the EXTENDED schema.

Example: Method node extracts an atom with relation type `extends` (not in schema). Intra-node detection flags it; discourse role = definition → high weight; validation accepts (evidence span present). Schema extends +`extends`. The Discussion node (topo-after Method) now extracts with `extends` in the enum — it can capture "this paper extends the μ(I) law" relations it would otherwise miss.

This is **single-pass, intra-extraction evolution** — structurally distinct from EDC's post-hoc and AutoSchemaKG's pre-extract.

### 3.6 Canonicalize (EDC-style) as the closing phase

After the DAG completes, run ONE canonicalize pass (merge near-duplicate schema elements added across many papers) to prevent bloat. Framed as "EDC's canonicalize phase adapted to an intra-DAG recurrence-gated scientific schema" — narrow but defensible (EDC has 10 citations in 2 years, no successors; memory `multischema-identity-direction-verdict`).

## 4. Ablation design (to produce the numbers)

20 papers, stratified, same set as the existing ablation. Three conditions:

| Condition | Evolution timing | Discourse weight | Cross-node recurrence |
|---|---|---|---|
| A: evo-OFF (baseline) | none | — | — |
| B: evo-ON post-hoc (current) | after extraction | no | cross-paper min 3 |
| C: evo-ON intra-DAG (proposed) | during extraction | yes | intra-paper cross-node ≥2 |

Metrics:
- **gaps accepted** (A=0, B=?, C=?)
- **atoms extracted** (does C's forward-propagation yield more grounded atoms than B?)
- **downstream-node benefit** = atoms extracted by nodes AFTER an evolution point, using the extended schema, that would NOT have been extractable under the old schema (count atoms whose type/subtype/relation was added intra-pass)
- **schema bloat** (final enum sizes A vs B vs C; C should be ≤ B + canonicalize savings)

**Prediction**: C > B on accepted gaps + downstream-node benefit (because intra-paper cross-node recurrence fires earlier and forward-propagation lets later nodes use new slots). If C ≈ B, the intra-DAG angle is not worth the complexity — report honestly.

## 5. Implementation sketch (when we move past design)

1. `chained_extractor.py`: after each node's atoms are grounded, call a new `_detect_gaps_intra(node, atoms, structure_map)` that tags gaps with node_id + discourse_role.
2. New `intra_dag_evolver.py`: maintains a per-paper `gap_score` map; when a gap's score crosses threshold (cross-node ≥2 OR definition-role + evidence), call `validate_gap`; if accepted, `schema_manager.extend_*` + set a `schema_dirty` flag.
3. `chained_extractor`: before each node's extraction call, if `schema_dirty`, re-fetch `schema_prompt` (already easy — `schema_manager.get_schema_prompt()` reads current state).
4. After DAG: run `canonicalize` (dedup near-duplicates via embedding similarity, merge).

Engineering: medium. The DAG loop already exists; this adds per-node gap detection + a dirty-flag check before each node's LLM call. No rewrite of the three-phase pipeline.

## 6. Risks + TODOs

1. **Literature vacancy must be verified** before paper submission: search arXiv for "intra-extraction schema evolution" / "during-extraction schema update" / "online schema induction". If a 2025-2026 work already does mid-extraction evolution, pivot the framing to "discourse-role-weighted + evidence-anchored" (the two pieces that need the DAG).
2. **Schema bloat risk** in intra-DAG: without canonicalize, a long paper could extend many times. Canonicalize (§3.6) is mandatory, not optional.
3. **Non-determinism**: LLM extraction yield varies ~7× (memory); gap detection will too. Report aggregate over 20 papers, not single-paper.
4. **Forward-propagation causality**: to prove the extended schema CAUSED downstream atoms (not just correlation), the ablation must count atoms whose type was ADDED intra-pass and would have been REJECTED under the old schema — a precise counterfactual check.
5. **EDC framing risk**: "we adapt EDC's canonicalize" is narrow; reviewers may ask why not just use EDC. Answer: EDC is post-hoc and flat; our canonicalize operates on a recurrence-gated, discourse-weighted, intra-DAG-evolved schema — the inputs are different, not just the merge step.

## 7. What this unlocks for the paper

- C2 (self-evolving schema agent) upgrades from "trigger→validate→version (same as frontier, post-hoc)" to "intra-DAG, discourse-weighted, forward-propagating" — a structural differentiator.
- C5 ablation gains a third arm (C: intra-DAG) beyond A (off) / B (post-hoc) — the comparison that proves the intra-DAG angle is worth it.
- Closes the loop with C4 (three-phase extraction): the DAG + discourse roles are NOT just for extraction quality — they are the signal source for self-evolution. The extractor upgrade and the self-evolution upgrade are the same architectural investment.
