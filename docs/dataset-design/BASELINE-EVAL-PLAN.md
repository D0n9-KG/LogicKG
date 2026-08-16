# Baseline + Hard-Indicator Evaluation Plan

## Goal
Add same-class schema-KG baseline (EDC) + stronger indicators (beyond edge/node
counts) + downstream n-ary QA validation, so the system's advantage is
defensible to a CCF-A reviewer (not "we extract more edges").

## Baselines (3 arms, all deepseek, same papers)
1. **native-LLM** (DONE): free binary triplets, no schema, chunked full-paper.
   Shows bare LLM.
2. **EDC** (adapted, runnable): open-IE → schema definition → canonicalize
   (relations). Same-class self-evolving-schema-KG (arXiv 2404.03868). The
   critical comparison: EDC canonicalizes/merges relations post-hoc but does
   NOT split over-wide patterns and is binary triplets — our split + n-ary
   must show here. EDC's llm_utils + glm_embedder already patched for Paratera.
3. **ours** (v12): schema-restricted self-evolving n-ary hypergraph.

Papers: 0BFD / 5022 / C9726 (the 3 verified). EDC runs on same 3.

## Indicator system (4 axes, none = raw edge count)

### A. n-ary fidelity (core contribution)
- arity distribution + max_arity (already)
- equiv-binary info volume C(k,2) per arity-k edge (already)
- **fragmentation rate**: for native/EDC (binary only), cluster their
  triplets by shared-evidence-sentence (same source sentence = same n-ary
  relation shattered). Cluster size = how many binary fragments express one
  n-ary fact. Our n-ary edge of arity k replaces k-1 fragments. Reports:
  "native shatters each n-ary relation into N fragments; ours expresses it
  in 1 edge". This is the non-trivial structural advantage.

### B. key-relation coverage (gold-free, LLM-grounded)
- Generate a "key relations checklist" per paper: deepseek lists 15-20 core
  relations from full text (distinct prompt from extraction, to limit
  circularity).
- Each arm's graph matched against the checklist (semantic match: node
  surfaces + relation type, embedding-cos >= 0.6 or LLM judge).
- Report coverage@k: what fraction of key relations each arm captured.
- Circularity control: gold generation prompt ≠ extraction prompt; spot-
  check 5 relations/paper manually.
- NOTE: this is LLM-as-gold (known weakness) — report honestly as
  "LLM-estimated coverage, not gold".

### C. schema quality (self-evolution卖点)
- pattern count trajectory (already)
- near-dup pattern ratio (merge should reduce)
- split-fire rate (does split trigger on real data? — ablation showed 0,
  must diagnose)
- deprecated-pattern handling (deprecated kept for provenance, not re-advertised)

### D. downstream n-ary QA + source judge (the hard proof)
- Construct n-ary-requiring questions per paper: "which quantities does X
  depend on?" / "list all inputs of the constitutive law for Y" — answers
  are MULTI-entity sets, only n-ary graphs answer correctly (binary graphs
  miss the joint structure).
- Each arm: retrieve top-k graph relations relevant to Q (by node-surface
  match + embedding), feed to deepseek to answer.
- Judge: deepseek sees ONLY paper-fulltext + question + answer, NOT which
  graph/source. Judges correctness (answer entities all in paper + complete).
  Blind to arm = no circularity in scoring.
- Report: answer accuracy on n-ary questions. Hypothesis: ours >> native/EDC
  because only n-ary graphs preserve the multi-entity relation.

## Implementation order (each → run + inspect, per iteration protocol)
1. EDC baseline run on 3 papers (verify the patched llm_utils/glm_embedder
   work; dump EDC's extracted triplets + canonicalized schema). → inspect
   EDC output vs source.
2. Indicator A (fragmentation) script — applies to all 3 arms' dumps.
3. Indicator B (coverage) — gold checklist + matching. Spot-check 5/paper.
4. Indicator D (downstream QA) — construct Qs, retrieve, judge. The big one.
5. Indicator C (schema quality) — already mostly have data, just report.
6. Assemble comparison table: 3 arms × 4 indicators.

## Cost
- EDC: ~3-5 LLM calls/paper (OIE+SD+SC phases) × 3 papers.
- Coverage + QA judge: ~20-40 deepseek calls total. Feasible on deepseek.

## Verification limits (honest)
- CAN: n-ary fidelity (structural, deterministic), fragmentation (det),
  downstream QA accuracy (blind judge), schema trajectory (det).
- CANNOT (gold pushed to expert): true precision/recall. Coverage-B is
  LLM-estimated, flagged as such. QA judge is LLM (blind but not gold).

## Risk
- EDC patched but not run-verified yet. If EDC fails to run, fall back to
  native-only + cite EDC paper numbers (less ideal).
- Downstream QA construction quality determines the whole axis D — must
  construct questions that genuinely REQUIRE n-ary (binary-insufficient).
  Validate by: a binary graph provably cannot answer (missing joint info).
