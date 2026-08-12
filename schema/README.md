# GranularFlow-Bench Schema (v3, contribution-centric)

Formal JSON Schema definition: `granular_flow.schema.json`

## Design lineage (each change grounded)

- **v1** (DESIGN draft): three-tier (L1/L2/L3), L3 = FUNCTION_RELATION + COMPARISON_ARM + CAUSAL_ATTRIBUTION + RESEARCH_QUESTION. Design-only, no extraction tested.
- **v2** (DESIGN §4.1.1): added FUNCTION_RELATION subtype (constitutive_law|empirical_scaling|governing_equation|numerical_relation) + paper_type, after 9-paper coverage check.
- **v3** (current): **replaced FUNCTION_RELATION-as-core with CONTRIBUTION-as-reified-entity**. Triggered by first real extraction (v2 on 10 papers) showing FUNCTION_RELATION abused on experiment papers (Albert 1999 drag: 13 "formulas" instead of experimental findings). Grounded in ontology survey (SciClaim reification, Matter-of-Fact 2D classification, HyperRED qualifier, MAGIC conflict-as-graph).

## Why three tiers

- **L1 entities** — the parts (MATERIAL/PROPERTY/NUMERIC...). Borrowable from MuLMS.
- **L2 relations** — how parts assemble into facts (measures_property/condition_*). Borrowable from MuLMS.
- **L3 contributions** — what the paper contributes as a whole (a reified entity, not an edge). Granular-flow innovation; MuLMS stops at L1/L2.

## L3 design (the innovation)

A **CONTRIBUTION** is a first-class entity (per SciClaim `2021.emnlp-main.381` association reification — not an edge), with:
- **multi-label subtypes** (per Matter-of-Fact `2025.emnlp-main.203` 2D classification): a contribution can be simultaneously `experimental_finding` AND `supports a mechanism` — not mutually exclusive.
- 6 subtypes: `constitutive_law | experimental_finding | mechanism_analysis | theoretical_result | numerical_finding | integrative`.

**CONTRIBUTION_RELATION** is a directed edge between contributions (per HyperRED `2022.emnlp-main.688` hyper-relational structure): `supports | conflicts | depends_on | applies_in | derives_from`, optionally carrying a `qualifier` (condition/regime/range).

**Conflicts are first-class graph structure** (per MAGIC `2025.findings-emlp.466`) — not post-hoc detection. This is how multi-mechanism competition (μ(I) vs non-local; Coulomb vs viscoplasticity) is expressed: two mechanism_analysis contributions linked by a `conflicts` edge.

## What this schema does NOT claim (occupancy)

- NOT "invented schema induction" — DIAL-KG/AutoSchemaKG/LOGOS/AdaKGC occupy general schema induction.
- NOT "invented non-flat schema" — Complex Event Schema (EMNLP 2021) occupies graph schemas.
- Real cross-paper conflicting claims in scientific IE: **no prior art** (MAGIC uses synthetic conflicts; COVID-Fact generates counter-claims within one paper). Our schema is first if implemented.

## Validation status (honest)

- v3 extraction on 8 papers: feasible (L3 non-empty 8/8), key win = experiment-drag's 13 v2 "formulas" → 3 experimental_finding + 2 mechanism_analysis.
- silo-experiment: 4 `conflicts` detected — multi-mechanism competition surfaced.
- n=8, single seed, no gold, no expert, no κ — directional only. Full validation (expert audit + κ) pending.
- known issue: theory papers occasionally mislabeled as experimental_finding (prompt issue, not structural).

## Files

- `granular_flow.schema.json` — formal JSON Schema (validated: legal instance passes, illegal rejected, multi-label works)
- `../docs/dataset-design/DESIGN-v1.md` — design narrative (§4.1 = schema, §4.1.1 = v3 rationale, §4.1.2 = validation)
