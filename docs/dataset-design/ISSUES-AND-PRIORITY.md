# Issues backlog + priority (2026-08-14, pre-goal-compression)

Complete inventory of problems found in earlier discussion, with priority
assignment for the implementation phase. This file exists so a context
COMPRESS does not lose the list — the goal prompt references this file,
it does not rely on conversation memory. Read this FIRST when resuming.

## Priority 1 — load-bearing, do THIS round (the coherent set)

These are connected: split is the headline, but it naturally pulls in the
gate-circularity fix (deterministic triggers), the forward-bias fix
(retrace), and the bloat fix (merge/retire + the P-E1 catch-all).

STATUS (2026-08-14, goal phase): all 6 done. Detail in HYPERGRAPH-EVOLUTION.md.

| id | problem | fix this round | how | status |
|----|---------|----------------|-----|--------|
| A1 | evolution is accumulation, not evolution (split/merge 0 trigger) | YES | implement split_pattern + merge_patterns + retire | DONE: schema ops + deterministic triggers |
| P-E1 | dependency_relation catch-all (16/39 edges, pattern too coarse) | YES | split's testbed — split over-wide patterns by instance clustering | DONE: split fires on real 0BFD (3 clusters 27/8/4) |
| A4 | LLM-judge circularity (proposer=judge=auditor=deepseek) | YES | deterministic triggers (clustering/embedding) NOT LLM self-judgment | DONE: split/merge decide deterministically, LLM names only |
| A2 | single-direction forward bias (early papers extracted with narrow schema) | YES | retrace: re-attribute historical edges after repair + final-schema small-sample re-extract | DONE: +29% (12 relations) recovered, no hallucination |
| A5 | novelty occupied (DIAL-KG did merge/retire) | YES (positioning) | claim ONLY split+hypergraph+physics as novel; credit merge/retire to DIAL-KG | DONE: merge/retire credited to DIAL-KG (arXiv 2603.20059) |
| P-E3 | regime qualifier under-used (hypergraph's key feature idle) | YES | strengthen extractor prompt to force applies_in_regime qualifier + verify | DONE: 39/39 filled on re-extract |
| P-E2 | no provenance (cited work recorded as own) | YES | add cited_from qualifier + prompt guidance | DONE: cited_from 39/39 (this_work/prior_art/definition) |
| A6 | seed bias (no seed-sensitivity check) | YES | 3-seed ablation on deepseek (post-split) | RUNNING (3 seeds × 4 papers, final prompt) |

### EXTRA (user-directed, beyond original 7): single-paper hypergraph quality
User asked "did you actually look at the hypergraph?" then directed: iterate
the extractor until the hypergraph "completely + accurately expresses a paper"
(single-paper first, cross-paper later). This was NOT in the original goal's
7 tasks — it was the user catching that the headline "hypergraph" was in name
only (all arity-2). Done across v2->v12:
- arity: validate REJECTED n-ary (seed role_slots were fixed-length). Fixed:
  variadic role_slots (repeatable=True) + set/count matching. + prompt
  n-ary example + "coordinated entities share one edge" rule.
- over-long sections: 23k-char Discussion -> 0 edges (LLM drowned). Fixed:
  _chunk_text (>6k -> sentence-boundary chunks, multi-call).
- node dedup: cross-section surface merge. dup_excess 17 -> 0.
- metadata: InstanceHypergraph.metadata (title/authors/doi/year) + node
  source_paper (cross-paper attribution).
- relaxed validate_proposal: "reject definitions" was killing definitional
  RELATIONS (defines_composition etc). Fixed.
Result: 3 papers (1979/1990/2018) all produce real n-ary hypergraphs
(n_ary_ratio 0.40-0.68, arity up to 7, evidence verbatim, dup 0, metadata
captured). graph_quality.py + section_coverage_audit.py are the judges.
=> single-paper "reconstruct the paper" MET on 3 papers. See HYPERGRAPH-EVOLUTION
"Graph-structure iteration" + "THIRD PAPER" sections.

### Key iteration findings (see HYPERGRAPH-EVOLUTION.md "Manual inspection")
- split mechanism correct on synthetic; did NOT fire on real free-text
  dependency_type (continuous-gradient, 145/153 pairs cos>=0.55). FIXED by
  controlled-enum extraction (dependency_type ∈ {monotonic, derivation, analogy,
  composition}) + discrete-first clustering. Split's honest contribution =
  MECHANISM + the controlled-enum extraction that makes it fire on real papers.
- Retrace (A2): forward-only bias = +29% missed relations recovered by final-
  schema re-extract, all verbatim (no hallucination). grounding 0.943 (slightly
  under 0.95 bar — recall/precision tradeoff, reported honestly).
- merge/retire: 0 triggers on single paper (genuine no-dup); value is cross-
  paper (verified in ablation). merge/retire are DIAL-KG's — credited, not claimed.
- Embedding: Paratera GLM-Embedding 429s hard; added CST qwen3-embedding:8b
  fallback (separate uni-api, works). All embedding now robust (split/merge/semantic-dedup).
- New follow-up (deferred): recursive split (split's monotonic sub-pattern 27
  edges may conflate strong vs weak dependence). Not needed this round.

## Priority 2 — low-cost parallel (do if time, not blocking)

| id | problem | note |
|----|---------|------|
| A7 | corpus purity (880/2355 filter coarse) | already filtered, adequate for now |
| P-E4 | review/discourse content extracted as physical relations | minor filter, post-split |
| node-dedup | nodes dedup by nid string not entity | cross-instance entity normalization, later |
| qualifier-normalization | applies_in_regime="dense" vs "dense regime" fragmented | later |
| cross-paper-instance | each paper's instance is independent; paper-A's μ(I) and paper-B's μ(I) cannot be linked as the same relation | same root as retrace (intra=re-attribute, cross=merge instances). Note: schema IS shared cross-paper, only instances aren't. |

## MANDATORY iteration protocol (user-emphasized, non-negotiable)

After EVERY change (split, merge, retire, prompt change, retrace), MUST:
1. Run extraction on a real paper, dump the instance hypergraph.
2. Read the instance + the paper's source text side by side.
3. Concretely analyze: is the change doing what it should? Did it break
   something? What NEW problems appear? (This is how P-E1/E2/E3/E4 were
   found — grounding was 1.0 but抽检 exposed dependency_relation catch-all.)
4. Record findings to HYPERGRAPH-EVOLUTION.md under a "Manual inspection"
   entry, then iterate on the new problems.

This is the ONLY method that catches "numbers look good but the graph is
wrong". Do NOT skip it. Grounding/recall numbers are NOT a substitute for
reading the actual extracted graph against source. If a change passes
mechanism tests but you did not inspect实例+原文, the change is NOT done.

## Priority 3 — pushed back or resource-blocked (honest, NOT this round)

| id | problem | why deferred |
|----|---------|--------------|
| A3 | no gold recall | pushed to human-expert phase (user decision) |
| A8 | single seed + single model | Paratera: Kimi timeouts, Qwen/GLM return empty; only deepseek usable. multi-model not feasible. |
| A9 | baselines incomplete (native 3 papers, EDC 2/20) | engineering grind, parallelizable, not blocking main line |
| A10 | downstream benchmark weak (C2/C3 minimal only) | full benchmark is paper-writing phase |

## Verified prior-work map (DO NOT re-research, read full-text already)

| work | arXiv | does split? | does merge? | does retire? | on hypergraph? | physics? |
|------|-------|------------|-------------|---------------|----------------|----------|
| DIAL-KG | 2603.20059 | NO | YES (cross-batch canon) | YES (soft deprecate) | NO (triplet) | NO (K8s/news) |
| Hyper-KGGen | 2602.19543 | NO | NO | NO | YES (but skill-evo not schema) | NO |
| EDC | 2404.03868 | NO | values-only | NO | NO | NO |
| HyDRA | 2507.15917 | NO | NO | NO (narrowing only) | NO | NO |
| AutoSchemaKG | 2505.23628 | NO | NO | NO (post-hoc) | NO | NO |
| AdaKGC | 2305.08703 | NO | NO | NO (never delete) | NO | NO |
| "Agentic Ontology ESWC2026 (restaurant)" | — | FABRICATED, does not exist | — | — | — | — |

**Novelty = pattern-level split + hypergraph-topology repair + physics domain + verbatim-evidence anchor.**
merge/retire are DIAL-KG's first (cite as prior, do not claim).

## LLM-judge circularity verdict (DO NOT re-research)
- 2410.21819: switching models doesn't break self-preference (root=perplexity)
- 2310.01798: LLMs cannot intrinsically self-correct
- 2401.10020: self-rewarding via LLM-judge = circular anti-example
- ONLY path: deterministic external anchor (Constitutional AI 2212.08073 style)
- → split/merge/retire triggers MUST be deterministic (clustering/embedding), NOT LLM-judged

## Seed + retrace strategy (DO NOT re-research)
- seed defense: HyDRA-style (seed=domain primitives) + AdaKGC-style 3-seed ablation
- retrace: forward-only main + final-schema small-sample re-extract (3-5 papers) to quantify AdaKGC "Weak Transfer" bias. No full re-extraction (cost infeasible, no precedent).

## What verification can/cannot be done (honest)
- CAN: mechanism-level tests (split/merge/retrace unit+integration), sampling-audit vs source text, grounding non-regression (>=0.95), deterministic-trigger monotonicity, 3-seed variance.
- CANNOT (gold pushed to expert): real recall/precision numbers. Do not fake recall. "Verification" = mechanism + sampling, not recall digits.
- multi-seed via deepseek only (Paratera limit); 3 different seeds feasible.

## Rules (violated before, must not repeat)
1. No fake progress. grep/run before reporting.
2. No软点糊弄. fix or retract numbers that don't survive追问.
3. Find one -> scan same-class.
4. Novelty/existence judgments: read full-text, not abstract. (earlier misjudged DIAL-KG by abstract; fabricated "Agentic Ontology" placeholder)
5. Verify arXiv existence via export.arxiv.org/api/query (Semantic Scholar 429's).
6. LLM = deepseek only (Paratera others unusable).
7. Directional decisions -> ask user. Technical -> fix or research.
