# Progress Log

## Stage 1: Agent Core Implementation + 1 Paper Test ✅ COMPLETE

**Date**: 2026-08-12

### What was implemented
- `src/granular_agent/schema_manager.py` — append-only schema version manager with provenance (CHANGELOG.jsonl)
- `src/granular_agent/llm_client.py` — DeepSeek + Paratera API wrappers (chat + embedding)
- `src/granular_agent/extractor.py` — multi-LLM extraction + MARY fusion + passive gap detection
- `src/granular_agent/gap_discovery.py` — active cross-paper gap scan + evidence-linked validation
- `src/granular_agent/qa_generator.py` — QA pair generation (answers anchored to paper text)
- `src/granular_agent/agent.py` — main agent orchestrator (6 capabilities + 5 hooks + deterministic flow)
- `src/run_test.py` — test runner

### Test result (Jop 2006, PPR_B0E8916D4E19)
- **66 atoms extracted** (L1 entities + L2 relations + L3 contributions/relations/RQ/CLOSURE)
- **7 L3 CONTRIBUTIONs** with correct multi-label subtypes (constitutive_law, experimental_finding, mechanism_analysis, theoretical_result, scaling_law, integrative, numerical_finding)
- **5 QA pairs** generated with answers anchored to paper data (particle diameter=0.53mm, μ_s=0.279, I_0=16.5)
- **0 gaps detected** on this single paper — schema v4 covers Jop 2006's content
- **0 schema evolutions** — no gaps = no evolution triggered (expected for a well-fitting paper)
- Schema version stayed at v4.0

### Key observations
1. v4 schema (with CLOSURE, REGIME, split CONDITION) fits Jop 2006 well — no gaps
2. LLM correctly assigned multi-label subtypes (e.g. constitutive_law + theoretical_result)
3. QA answers are grounded in paper text (verified: 0.53mm, 0.279, 16.5 are real values from Jop 2006)
4. Single LLM (DeepSeek) works; multi-LLM fusion not yet needed for this test

### What's next (Stage 2)
- Run on 50 papers across subdomains to trigger self-evolution
- Papers from different subdomains (experiment/DEM/theory) are more likely to expose schema gaps
- Run ablation: self-evolution ON vs OFF, compare extraction quality (C5)
