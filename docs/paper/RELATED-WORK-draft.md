# Related Work Section Draft

## 2. Related Work

### 2.1 LLM-based Schema-Inducing KG Construction

**EDC** (EMNLP 2024) [1] decomposes KG construction into Extract-Define-
Canonicalize: schema-free LLM extraction + post-hoc canonicalization via
Schema Retriever. Schema is a flat predicate set; no pattern-level topology;
no top-down split. Partial F1 on WebNLG: GPT-4 0.820, GPT-3.5 0.794.

**DIAL-KG** (DASFAA 2026) [2] introduces dynamic schema induction + evolution-
intent assessment for incremental KG construction. Schema is a normal graph
(binary relation schemas reified to triples); evolution = bottom-up merge +
retire with cross-batch canonicalization. No pattern-level split, no pattern
dependencies, no constraint-violation detection. Uses Qwen-Max for extraction
+ DeepSeek-V3 as judge. WebNLG F1 0.865; 15% fewer relation types; 98%
precision on evidence-backed soft deprecations. **Closest prior work** —
differs from ours in: (1) flat schema vs meta-hypergraph topology, (2)
bottom-up only vs + top-down split, (3) no constraint detection.

**AutoSchemaKG** (2025) [3] induces schemas from text simultaneously with
triple extraction, using conceptualization. Evaluates schema quality via
entity/event/relation typing tasks (FB15kET, YAGO43kET). No evolution; schema
is one-shot post-hoc.

**LOGOS** (2025) [4] automates grounded-theory coding from documents. Schema
= single-layer hierarchical typed graph (5 binary taxonomic relation types).
Evolution ops: merge/subsume/drop/add/replace — NO split, NO retire, NO
pattern-level split. Explicitly states limitation: "does not yet capture
richer structures such as causal, temporal, or processual relations."

**AgentCAT** (2026) [5] (chemistry catalysis): property-graph + single-layer +
add-only under a conservative policy. Achieves convergence (Fig 4
bootstrapping-then-convergence) but never splits/merges patterns. No
pattern-level topology, no constraint detection. Uses expert blind
evaluation (not gold F1).

### 2.2 N-ary / Hypergraph Knowledge Representation

**Text2NKG** [6]: fine-grained n-ary relation extraction → n-ary KG. Variable
arity, span-tuple classification. Direct prior on instance-layer n-ary;
does NOT evolve schema. **HyperRED** [7]: hyper-relational extraction
(triplet + qualifier), cube-filling model. Instance-layer qualifier; fixed
schema. **HEHRGNN** [8]: MELTS hyperedge + hyper-relational into one
instance-level hyperedge; no schema layer. A survey [9] notes "hypergraph
representation learning often overlooks entity roles in hyperedges" and
that all methods are single-structure (no schema/instance layering).

### 2.3 Our Position

We compose what no single prior work does: (1) schema-as-hypergraph (meta-
hyperedge connecting type-slots, not flat predicates — arXiv "meta-hypergraph"
zero hits), (2) pattern-level split (top-down, DIAL-KG/AgentCAT/LOGOS don't),
(3) pattern dependencies + constraint-violation detection (DIAL-KG can't),
(4) growable families + bounded operations (AdaKGC fixed-top + AgentCAT
conservative + ANNEAL bounded-edits, composed — no single work composes all
four).

[1] EDC, EMNLP 2024 main.548
[2] DIAL-KG, arXiv 2603.20059, DASFAA 2026
[3] AutoSchemaKG, arXiv 2505.23628
[4] LOGOS, arXiv 2509.24294
[5] AgentCAT, arXiv 2602.18479
[6] Text2NKG, arXiv 2310.05185
[7] HyperRED, EMNLP 2022, declare-lab
[8] HEHRGNN, arXiv 2602.18897
[9] n-ary KR survey, arXiv 2506.05626
