# System Audit: Claim vs Reality (2026-08-13)

Full audit of every module. Each entry: what the paper/design CLAIMS, what the code REALITY is, and verdict (FIX or WITHDRAW). Based on runtime logs + code inspection, not just code reading.

## CRITICAL (数字直接误导)

### #1 gap_discovery.detect_gaps — BLIND DETECTOR
- **CLAIM**: "detect schema gaps" / "0 gaps on mature v4"
- **REALITY**: enum-membership check on EXTRACTED atoms. Only sees LLM-invented out-of-enum types. Blind to: (a) recall gaps (paper has concept, LLM didn't produce atom), (b) misclassification (wrong type chosen but falls in enum), (c) misbinding (wrong subject but type ok), (d) structural gaps (concept clusters with no schema slot).
- **EVIDENCE**: 49 papers, 0 gaps detected. But Jop 2006 Method section (5246 chars) only extracted 9 atoms — obvious recall漏. Detector cannot see this.
- **VERDICT**: FIX — add recall-aware probe (LLM re-scan section for missed entities vs schema) + misclassification probe (sample atoms, ask if type is right). The "0 gaps = v4 complete" conclusion is INVALIDATED.

### #2 grounding.ground_atoms — CIRCULAR
- **CLAIM**: "99.97% verbatim grounding"
- **REALITY**: evidence_span is LLM-copied verbatim by instruction. Checking if it appears in text = checking if LLM obeyed copy instruction. 100% = LLM compliance, NOT extraction correctness. Wrong span picked / wrong binding still grounded.
- **VERDICT**: FIX — add support verification (does the span actually support the atom's type/binding? NLI or rule check). Grounding rate will drop to real value.

### #3 qa_generator — DOES NOT TEST EXTRACTION
- **CLAIM**: "QA grounded in paper text" / one of 3 RAGA differences
- **REALITY**: answer = the SAME evidence_span the extractor produced. QA tests "can LLM write a question for this span", NOT "is the atom correct". A wrongly-extracted atom yields a valid QA pair. QA grounded ≠ extraction correct.
- **VERDICT**: FIX — QA must test something the extractor didn't produce (e.g., ask about a paper fact, check if extraction would support that answer). Or downgrade claim to "answer appears in paper" (weak).

### #4 _detect_gaps post-extraction — DOUBLE-BLIND
- **CLAIM**: "intra-DAG + post-hoc dual detection"
- **REALITY**: same blind detector run twice. Double-running a blind detector is still blind.
- **VERDICT**: WITHDRAW the "dual detection" claim. Keep one detector, fix it.

## HIGH (死代码 / 盲)

### #5 adaptive fission — DEAD CODE
- **CLAIM**: "low confidence → split node into focused sub-calls" (design feature)
- **REALITY**: 49 papers, 0 fissions. LLM self-confidence min 0.85 / mean 0.93 — never below 0.40 threshold. Mechanism never triggers.
- **ROOT CAUSE**: LLM confidence is uncalibrated, uniformly high (#7).
- **VERDICT**: WITHDRAW as feature, OR replace trigger signal (e.g., atom density per section-length, not LLM confidence).

### #6 find_rebind_candidates — BLIND TO REAL REBINDS
- **CLAIM**: "discourse-role rebind detection"
- **REALITY**: 49 papers, 0 candidates. Groups L1 by surface string + flags same surface across definition vs non-definition roles. Found a REAL rebind in Jop 2006 (I_0 extracted as both MATERIAL_PARAMETER and DIMENSIONLESS_NUMBER, same node) — detector missed it because both atoms have role=observation (not definition-vs-other).
- **ROOT CAUSE**: rebind = same concept under different binding. Surface-string + role matching cannot catch same-surface-across-TYPE (the actual misclassification signal).
- **VERDICT**: FIX — detect same surface form assigned DIFFERENT entity_types (regardless of role). That's the real misclassification signal.

### #7 _mean_confidence — UNCALIBRATED
- **CLAIM**: "confidence drives fission"
- **REALITY**: LLM self-confidence 0.85-1.0, never validated against correctness. Drives fission to be dead code.
- **VERDICT**: WITHDRAW confidence-as-signal. If fission kept, use objective signal (atom density, section length).

### #8 active_gap_scan — BLIND (same as #1)
- **CLAIM**: "cross-paper recurring gap scan"
- **REALITY**: scans for out-of-enum types across papers. Same blindness as #1. Never triggered in any run.
- **VERDICT**: FIX with #1 (recall-aware probe works cross-paper too).

## MEDIUM

### #9 grounding.lookup — NEAR-DEAD
- **CLAIM**: "LLM re-checks flagged atoms"
- **REALITY**: triggers on ungrounded/low-conf atoms. Since grounding is circular (always passes), lookup rarely fires. Phase 2 lookup is near-dead.
- **VERDICT**: becomes live AFTER #2 fixed (real grounding filters atoms → lookup re-checks the filtered-out ones).

### #10 schema_manager — NO BLOAT HANDLING
- **CLAIM**: "append-only versioning"
- **REALITY**: no dedup/merge/canonicalize. Cross-domain test bloated to 36 subtypes + 40 relations.
- **VERDICT**: FIX — add EDC-style canonicalize phase (per design doc SELF-EVOLUTION-v2.md §3.6).

### #11 structure_mapper stability — UNDERTESTED
- **CLAIM**: "structure map stable across runs"
- **REALITY**: tested on 1 paper (Jop) × 2 runs only.
- **VERDICT**: test on 5+ papers × 3 runs before claiming stability.

### #12 MARY fusion — NOT INTEGRATED
- **CLAIM**: C4 capability
- **REALITY**: validated on 9 papers separately, not in 49-paper mainline (single-LLM).
- **VERDICT**: either integrate + measure at scale, or downgrade to "auxiliary validated separately".

## SUMMARY
- 4 CRITICAL: 3 FIX (#1 recall+misclass, #2 support-verify, #3 QA correctness) + 1 WITHDRAW (#4 dual-detection)
- 4 HIGH: 2 FIX (#6 rebind-across-type, #8 recall cross-paper) + 2 WITHDRAW (#5 fission, #7 confidence-signal)
- 4 MEDIUM: 3 FIX (#9 lookup-after-#2, #10 canonicalize, #11 stability-test) + 1 downgrade (#12 MARY)

## WHAT THIS MEANS
The "0 gaps on v4" and "99.97% grounding" were both artifacts of blind/circular detectors. The real extraction quality is UNKNOWN (could be better or worse than claimed — we have no signal). Before any CCF-A claim, must:
1. Fix #1 (recall-aware gap detection) — answers "is v4 really complete"
2. Fix #2 (support verification) — answers "are grounded atoms actually correct"
3. Fix #6 (rebind-across-type) — surfaces real misclassification
Then re-measure. The real numbers will be lower but honest.

## FIX LOG (2026-08-13)

### #6 rebind detector — FIXED ✅
- Replaced surface+role matching (0 candidates) with surface+TYPE matching.
- Jop 2006 test: 0 → 4 real misclassification candidates (I_0 as both MATERIAL_PARAMETER and DIMENSIONLESS_NUMBER; rough planes as both BOUNDARY_CONDITION and DEVICE; flowing layer thickness as both MEASUREMENT and PROPERTY).
- Detector now surfaces real type-confusion, not just role-shift.

### #1 recall-aware gap detection — FIXED ✅
- Added `recall_gap_probe`: LLM re-scans each section for concepts needing a NEW schema slot that enum-miss cannot see (silent extraction failure).
- Integrated into intra-DAG flow (1 extra call/node).
- Added evidence gate to `validate_gap`: rejects gaps without verbatim evidence_span (prevents probe from fabricating slots).
- **Jop 2006 test (mature v4): 0 → 2 real extensions** (shear_band, hysteretic_phenomenon, both with verbatim evidence).
- **CONFIRMS user's intuition**: v4 is NOT complete. Old detector's "0 gaps" was blindness, not schema completeness. Recall probe finds real漏抽 even on mature schema.

### Remaining issue (TODO, not blocking)
- Recall probe tends to propose concepts as `entity_type` when they should be subtypes or aren't entity-like (e.g. "shear_band" is a phenomenon/process, not an entity). `validate_gap` should also judge the CORRECT gap_type dimension, not just accept the probe's proposed type.
- This is a precision issue (some accepted extensions are mis-typed), not a recall issue (the concept IS漏抽). Fix is in validator prompt refinement.

### What the fixes PROVE
- The "0 gaps on v4" conclusion was a detector artifact. With recall-aware + cross-type detection, mature v4 surfaces real漏抽 (2 on Jop alone, 1 paper).
- The "99.97% grounding" was a separate circular artifact (still unfixed — #2 next).
- These two together mean: prior "抽取器质量硬" and "自进化在成熟 v4 无差异" conclusions were BOTH built on blind/circular detectors. Real numbers will differ.

## FIX LOG 2 (2026-08-13, goal mode)

### #2 grounding circularity — FIXED ✅
- Two-layer grounding: layer1 (span in text, LLM compliance) + layer2 (_supports: token-set Jaccard ≥0.5 between atom core values and span).
- layer2 breaks circularity: span must be ABOUT the atom (core tokens appear), not just in paper.
- Token-set matching tolerates word-order/inflection/LaTeX form differences ("flowing layer thickness" vs "thickness of the flowing layer" → both match).
- Jop 2006 real numbers: in_text 0.945, supported 0.655, grounded 0.618 (pre-lookup) → 0.971 (post-filter). Was 99.97% (circular).

### #9 lookup bypass — FIXED (new soft point found via 扫同类) ✅
- Found during #2 fix: lookup() upgraded atoms to grounded=True using ONLY layer1 (span in text), bypassing layer2 support check. This reintroduced circularity via LLM-found spans.
- Fixed: lookup-upgraded atoms must re-pass BOTH layers (in_text AND _supports).
- This was a NEW soft point discovered by 扫同类 (discipline #3) — same LLM-span root, found while fixing #2.

### Perturbation validation (proves support check is non-circular) ✅
- baseline: 97/125 supported
- swap-spans perturbation (each atom gets a WRONG atom's span): 97→9 supported (−91%, monotone decrease)
- null perturbation (no change): 97→97 (sanity)
- Verdict: support_rate is a real, falsifiable metric — NOT a tautology like the old 99.97%.

### Same-root scan (discipline #3) — QA still pending
- QA answer = evidence_span (same LLM-copied span). QA grounded has same circularity as old grounding. → #3 to fix next.
- active_gap_scan uses same blind enum-miss detector → fixed with recall_probe (already done).

### #2-validator gap_type correction — FIXED ✅
- validate_gap now judges the CORRECT schema dimension (entity_type vs subtype vs relation) and rejects phenomena-as-entity (shear_band, hysteresis).
- Jop 3 runs: run1 8 gaps→0 accepted (all mis-typed rejected), run2 37 gaps→1 accepted (visco-plastic fluid, borderline), run3 2 gaps→0 accepted.
- Validator now strict (good) — but accept rate very low.

### NEW SOFT POINT: recall probe variance (discipline #4, found during #2-validator test)
- recall_gap_probe produces 2-37 gaps on same paper across 3 runs (huge variance).
- The probe itself is LLM-driven and unstable. Most gaps are then rejected by validator (mis-typed).
- Net: intra-DAG self-evolution produces ~0-1 extension per paper with high variance.
- This affects stage 2 (self-evolution effectiveness) — must aggregate over 20 papers to see if signal is real.
- TODO for stage 2: run 20 papers × multi-seed to average out probe variance.

### NEW SOFT POINT: validator near-duplicate blindness (found during arm C)
- validator accepts surface_tension and roughness as new entity_type, but these are PROPERTY (already in enum).
- Schema got polluted: ROUGHNESS FRACTAL DIMENSION added (should be PROPERTY).
- validator's "distinct from existing?" check (criterion #2) not catching near-duplicates — LLM judge too loose.
- FIX (after arm C completes, to avoid mid-run changes): add embedding/lexical near-duplicate check before accept — if candidate >0.85 similar to existing enum value, reject and suggest existing.
- This is a PRECISION bug (recall is fine — concepts ARE漏抽; but they're being added as wrong-type duplicates).

### Stage 2 arm C (intra-DAG, 1 seed, 20 papers) RESULT
- 20/20 papers, 1101 atoms, 493 calls (24.6/paper — high due to recall probe 1 call/node)
- 6 extensions accepted across 5 papers (surface tension, roughness x3, extends, scaling_law)
- final schema v4.2
- REAL support rate (Phase2-pre): ranges 0.68-1.0 (real extraction quality, was masked by circular 99.97%)

### Stage 2 CRITICAL BUG: no canonicalize → bloat
- "roughness" added 3 times (PPR_D5FBEE49, PPR_79C1662F, PPR_7D2D8EA1) — same concept, schema bloats.
- No dedup/merge in SchemaManager.extend_*.
- This confirms audit #10 (no bloat handling) is now a REAL problem, not theoretical.
- Also: surface_tension/roughness accepted as entity_type but should be PROPERTY (validator near-duplicate blindness, already logged).
- TODO: implement EDC-style canonicalize (stage 2 step ⑦) + validator near-duplicate check BEFORE arm B completes (so arm B doesn't bloat same way).

### arm B (post-hoc) RUNNING — for intra vs post comparison

### Stage 2 ⑦ canonicalize + validator near-dup gate — FIXED ✅
- validator: deterministic near-duplicate gate (token Jaccard >=0.5 with existing enum in SAME dimension) BEFORE LLM judge. surface_tension/roughness → rejected as PROPERTY near-dup. extends/scaling_law → pass.
- canonicalize(): EDC-style merge of near-duplicate enum values (token Jaccard >=0.7), run after batch. Tested: SURFACE_TENSION merged into SURFACE TENSION.
- Bug fix: apply_schema_extension was using detector's gap_type not validator's CORRECTED gap_type (fixed — now uses validated["gap_type"]).

### Stage 2 DECISION (降级, per discipline #5)
- arm C (intra-DAG) 6 extensions vs arm B (post-hoc) 0 — but 4/6 were bloat/mis-typed (now preventable with fixes above).
- arm B used blind enum-miss detector (no recall probe) — unfair comparison.
- Self-evolution UNSTABLE on mature v4 (high variance, quality issues). Per discipline #5 诚实降级: self-evolution downgraded to "system capability" (not main contribution). Forward propagation mechanism confirmed (arm C跨篇 v4.0→4.2 累积). Main line → extraction + downstream.
- Stage 2 status: ⑥ done (comparison), ⑦ done (canonicalize). Moving to stage 3.

### Stage 3 ⑨ downstream task 1 — NOT DISCRIMINATIVE (honest finding)
- Built multi-mechanism claim verification from 14 papers' atoms (19 claims, 20 relations).
- Perturbation (swap supports<->conflicts) barely drops score (0.1) — NOT discriminative.
- ROOT CAUSE: 0 conflicts extracted across 14 papers! Relation distribution:
  applies_in=2, applies_in_regime=7, derives_from=7, supports=2, generalizes=2, conflicts=0
- **schema v4 "multi-mechanism competition" claim is NOT supported by extraction data.**
  applies_in_regime was designed as regime-complementary (not conflict), and became
  the extractor's escape hatch — conflicts almost never captured.
- This invalidates a key paper claim ("schema captures multi-mechanism competition").
- FIX needed: either (a) extractor prompt must push conflicts, or (b) downgrade the
  competition claim to "schema can represent regime-complementarity" (honest).
- Per discipline #1 (不准糊弄): cannot write "captures competition" with 0 conflicts.

### conflicts extraction — STILL WEAK after prompt fix
- Added CONTRIBUTION_RELATION guidance (conflicts/extends) to extractor prompt.
- Jop 2006 test: 1 CONTRIBUTION_RELATION (bounds_applicability_of) — still 0 conflicts.
- LLM prefers bounds_applicability_of/applies_in_regime over conflicts (more "polite").
- HONEST: schema v4 conflict capture is weak. The "multi-mechanism competition"
  framing is aspirational, not empirically supported.
- Paper claim must be downgraded: "schema can represent regime-complementarity
  and applicability bounds" (not "captures competition/conflicts").

### EDC baseline status (实跑)
- EDC fully adapted: Kimi-K2.6 (urllib, not openai SDK which had conn errors) + GLM-Embedding-2 (Paratera API, HF blocked) + chunking (8k/chunk, official EDC guidance for long docs) + max_tokens 4096 + oie_template "Triplets:" suffix + API key .strip() (was causing invalid header → all OIE=0).
- PPR_8E92BEDEFBD4 (6 chunks): 246 OIE triplets, 0 canonicalized to our 9-relation schema (canon all None — EDC free relations like enables/models/predicts don't match our schema).

### BASELINE CALIBRATION ISSUE (重要)
- EDC is schema-free OpenIE (extracts free relations: enables/models/predicts).
- Our system is schema-restricted (atoms must match v4 enum).
- Direct P/R comparison is unfair: EDC's free relations ≠ our 9 schema relations.
- Fair comparison must be on RAW triplets/atoms count (both extract physical content) OR provide EDC a wider schema.

### EDC AS BASELINE — AGE/RACECCEPTANCE (实查 2025-2026)
- GraphJudge (EMNLP 2025 main): baselines = GPT-4o/4o-mini + iText2KG + PiVe + KGGen + RAKG. EDC NOT used.
- LKD-KGC (2025 arxiv): uses EDC + AutoKG + KBTE.
- SF-GPT (2025 Neurocomputing): uses EDC.
- iText2KG (2024, arXiv 2409.03284): appears in BOTH GraphJudge and LKD-KGC baseline lists → NEWEST standard baseline.
- VERDICT: EDC still acceptable (275 cites, schema-based KGC rep) but NOT the 2025 main-conf standard. iText2KG is the newer standard. Reviewers may ask why not iText2KG/PiVe/KGGen.
- RECOMMENDATION: add iText2KG as primary baseline (newer, main-conf accepted) + raw LLM + EDC (already running).
