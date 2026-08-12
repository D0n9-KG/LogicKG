# Schema Validation (v2) — First Real Extraction

**Date**: 2026-08-12
**Verdict**: schema FEASIBLE (extractor can extract), but FUNCTION_RELATION abused on non-formula papers → supports the v3 CONTRIBUTION redesign.

## What was tested
First-ever real extraction (not keyword regex). v2 schema on 10 papers spanning types (rheology/elasticity/experiment/DEM/theory/kinetic/silo/nonlocal/review/scaling). deepseek-chat, temp 0.

## Results
- 8/10 succeeded (2 parse_fail — long papers, JSON truncated; prompt issue not schema).
- 523 atoms total across 8 papers. L3 non-empty on all 8 (kill point 0/8 empty, threshold was >50%).
- All L3 elements appeared: FUNCTION_RELATION / COMPARISON_ARM / CAUSAL_ATTRIBUTION / RESEARCH_QUESTION.
- All FUNCTION_RELATION subtypes used: constitutive_law / empirical_scaling / governing_equation.
- paper_type inferred correctly (rheology/experiment/theory/DEM/review).

## Key finding: FUNCTION_RELATION is a trash bin on experiment papers
- experiment-drag (Albert 1999): 13 FUNCTION_RELATION atoms in L3. But that paper's core is an experimental finding, NOT 13 formulas. Extractor stuffed every observed relation into FUNCTION_RELATION.
- This DIRECTLY confirms the user's concern: L3 centered on FUNCTION_RELATION (formula) forces non-formula papers to abuse it.
- Supports the v3 redesign: replace FUNCTION_RELATION with CONTRIBUTION + subtype (experimental_finding as its own subtype, not stuffed into formula).

## What this IS / IS NOT
- IS: evidence that schema is feasible (not just plausible), and that the formula-centric L3 design is wrong (user's concern was right).
- IS NOT: evidence schema is correct (no gold, no expert, n=8 single-seed).

## Limitations (honest)
- n=8, single seed, no gold — directional only.
- No verifier — "extracted" ≠ "correct". FUNCTION_RELATION abuse inferred from counts, not human audit.
- 2 parse_fail on long papers — prompt complexity issue.

## Next
- Wait for ontology-survey agent (a3d498dae0fddae6d) — borrow methods for contribution-classification.
- Redesign v3 based on survey + this finding: CONTRIBUTION + subtype (constitutive_law/experimental_finding/mechanism_analysis/theoretical_result/numerical_finding) replacing FUNCTION_RELATION.
- Re-run extraction on v3, compare with v2 — does experiment-drag's 13 "formulas" become experimental_findings?

## Files
- `extract_v2_schema.py` — the test script
- `.research_tmp/granular-benchmark/schema_validation_results.jsonl` — raw results
