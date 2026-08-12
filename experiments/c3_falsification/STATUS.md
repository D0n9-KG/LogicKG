# C3 Falsification Experiment — Status

**Date**: 2026-08-12
**Verdict**: INCONCLUSIVE — design flaws exposed, not a C3 kill. Deferred to post-gold phase.

## What was tested
Minimal falsification: does extraction quality (reference-free verifier-supported fraction) change when schema evolves from v1 (flat MuLMS-style) to v2 (L3 higher-order)?

## Result (1 paper, smoke test)
- v1 flat: 40 atoms, 35 supported, frac=0.875
- v2 L3:   26 atoms, 25 supported, frac=0.962

## Why inconclusive (design flaws exposed)

1. **Atom count dropped (40→26)**: v2's more complex schema made the extractor conservative, extracting fewer atoms. frac rose — but likely because "fewer extracted = higher quality", NOT because schema evolution improved quality. Confound: atom-count effect.
2. **No L1/L2 vs L3 split**: v2 frac mixes L1/L2 atoms (should be comparable to v1) with L3 atoms (harder to verify). Cannot separate "schema evolution effect" from "L3 elements harder to verify".
3. **Reference-free verifier**: the LLM-judge has a known blind spot (the rebind finding — LLM judges miss semantic rebinding). Without gold, the verifier's "supported" verdict is itself uncertain.

## What this IS evidence of (honest, single paper)
- Schema complexity affects extractor behavior (v2 extracted fewer atoms). This is a SIDE observation supporting C4 (schema is not neutral — it shapes extraction), but single paper, not a finding.

## Why deferred (not killed)
- C3 is the ceiling contribution, falsifiable. This test could not falsify it — the confounds prevent a clean yes/no.
- The proper test requires gold: compare v1/v2 extraction against expert-verified gold, not against a reference-free verifier.
- Decision: build the dataset (gold) first (C1+C2+C4 floor), then test C3 with gold-anchored measurement.

## What this experiment must NOT be used for
- NOT a C3 kill (cannot falsify with these confounds)
- NOT a C3 confirmation (single paper, design flaws)
- NOT a dataset-quality input (separate pipeline with expert verification handles that)

## Files
- `schema_switchable_extractor.py` — the test script (kept for reference)
- `.research_tmp/granular-benchmark/c3_results.jsonl` — 1-paper smoke result (kept)
