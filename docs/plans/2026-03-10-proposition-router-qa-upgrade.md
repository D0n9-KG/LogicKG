# Proposition-Aware QA Router Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade Ask into a proposition-aware multi-route GraphRAG pipeline that can answer both paper-detail questions and foundational domain questions by combining planner-guided retrieval, direct retrieval over `LogicStep / Claim / Proposition`, textbook-first routing when appropriate, and sentence-level grounding.

**Architecture:** Keep `/rag/ask_v2` as the public API, but insert a lightweight LLM planner ahead of retrieval. The planner emits intent, retrieval plan, and per-corpus rewritten queries. Retrieval then runs over multiple corpora in parallel: paper chunks, logic steps, claims, propositions, and textbook fusion/textbook graph rows. The final evidence bundle must be grounded back to sentence-level support and must preserve a full provenance chain from answer -> structured evidence -> chunk/chapter sentence.

**Tech Stack:** FastAPI, Neo4j client helpers, LangChain FAISS, Pydantic, React, TypeScript, Pytest, Vitest

---

### Task 1: Lock the new QA contracts in tests

**Files:**
- Create: `backend/tests/test_rag_planner.py`
- Create: `backend/tests/test_rag_structured_retrieval.py`
- Modify: `backend/tests/test_rag_service.py`
- Create: `frontend/tests/askPropositionGraph.test.ts`
- Modify: `frontend/tests/rightPanelAskSummary.test.tsx`

**Step 1: Write the failing planner contract test**

Add a backend test for a single LLM planner output shaped like:

```python
{
    "intent": "foundational",
    "retrieval_plan": "textbook_first_then_paper",
    "main_query": "finite element method assumptions",
    "paper_query": "finite element method assumptions in this paper",
    "textbook_query": "finite element method definition assumptions discretization",
    "proposition_query": "finite element method assumptions proposition",
    "confidence": 0.88,
}
```

Assert:
- invalid enum values are rejected
- missing `main_query` falls back to planner failure handling
- planner fallback returns a deterministic default plan without throwing

**Step 2: Run the planner test to verify it fails**

Run: `pytest backend/tests/test_rag_planner.py -q`
Expected: FAIL because no planner module or response schema exists yet.

**Step 3: Write the failing structured retrieval and grounding tests**

Add backend tests covering:
- direct retrieval of `LogicStep`, `Claim`, and `Proposition`
- foundational questions preferring textbook/proposition hits before paper chunks
- paper-detail questions preferring claim/logic hits from the target paper
- proposition rows carrying provenance back to source claim or mapped textbook entity
- sentence grounding rows preserving `quote`, `chunk_id` or `chapter_id`, and line spans when available

Use a compact fake result set like:

```python
[
    {"kind": "claim", "id": "cl-1", "text": "FEM improves stability.", "score": 0.82},
    {"kind": "proposition", "id": "pr-1", "text": "Finite element discretization stabilizes PDE solving.", "score": 0.79},
]
```

**Step 4: Run the structured retrieval tests to verify they fail**

Run: `pytest backend/tests/test_rag_structured_retrieval.py backend/tests/test_rag_service.py -q`
Expected: FAIL because the Ask pipeline does not yet retrieve or return structured evidence / sentence grounding.

**Step 5: Write the failing frontend Ask graph test**

Create a frontend test asserting Ask graph building can render proposition-aware results:

```ts
{
  structured_evidence: [
    { kind: 'proposition', proposition_id: 'pr-1', text: 'Finite element discretization stabilizes PDE solving.' }
  ],
  grounding: [
    { source_kind: 'proposition', source_id: 'pr-1', quote: 'Finite element method discretizes the domain.' }
  ]
}
```

Assert:
- proposition nodes render as a distinct kind
- proposition nodes can connect to claim / logic / textbook entity nodes
- grounding rows are surfaced in the Ask right panel summary or evidence detail

**Step 6: Run the frontend Ask tests to verify they fail**

Run: `npm test -- --run tests/askPropositionGraph.test.ts tests/rightPanelAskSummary.test.tsx`
Expected: FAIL because the frontend types and graph builder do not yet understand proposition or grounding records.

**Step 7: Commit the red tests**

```bash
git add backend/tests/test_rag_planner.py backend/tests/test_rag_structured_retrieval.py backend/tests/test_rag_service.py frontend/tests/askPropositionGraph.test.ts frontend/tests/rightPanelAskSummary.test.tsx
git commit -m "test: lock proposition-aware QA contracts"
```

### Task 2: Add proposition and structured-corpus exporters in Neo4j helpers

**Files:**
- Modify: `backend/app/graph/neo4j_client.py`
- Modify: `backend/tests/test_fusion_query_metadata.py`
- Modify: `backend/tests/test_rag_structured_retrieval.py`

**Step 1: Add a Proposition exporter for retrieval**

Implement a Neo4j helper that exports proposition texts with provenance. The method should mirror the existing `list_claim_similarity_rows()` and `list_logic_step_similarity_rows()` helpers:

```python
def list_proposition_similarity_rows(self, paper_id: str | None = None, limit: int = 200000) -> list[dict]:
    ...
    return [
        {
            "node_id": "pr-1",
            "paper_id": "doi:...",
            "text": "canonical proposition text",
            "source_kind": "claim",
            "source_id": "cl-1",
        }
    ]
```

Use both claim-origin propositions and textbook-origin propositions where possible. Do not duplicate rows for the same `prop_id`.

**Step 2: Add retrieval-oriented readers for structured Ask evidence**

Add explicit readers for:
- `LogicStep` rows with summary + evidence chunk ids
- `Claim` rows with claim text + evidence quote + evidence chunk ids
- `Proposition` rows with canonical text + `MAPS_TO` or `EvidenceEvent` provenance

Keep them query-oriented, not UI-oriented. The service layer should not have to reconstruct the provenance chain from raw graph traversals later.

**Step 3: Add a sentence-grounding helper**

Add a helper that can resolve structured evidence back to textual support:

```python
def get_grounding_rows_for_structured_ids(self, ids: list[dict], limit: int = 200) -> list[dict]:
    ...
```

Return rows shaped for Ask:
- `source_kind`
- `source_id`
- `quote`
- `chunk_id` and `md_path` for paper support
- `textbook_id`, `chapter_id` for textbook support
- `start_line`, `end_line` when known

**Step 4: Run targeted backend tests**

Run: `pytest backend/tests/test_rag_structured_retrieval.py backend/tests/test_fusion_query_metadata.py -q`
Expected: PASS

**Step 5: Commit the exporter layer**

```bash
git add backend/app/graph/neo4j_client.py backend/tests/test_fusion_query_metadata.py backend/tests/test_rag_structured_retrieval.py
git commit -m "feat: expose proposition and grounding retrieval helpers"
```

### Task 3: Build multi-corpus QA indexes and retrieval primitives

**Files:**
- Modify: `backend/app/vector/faiss_store.py`
- Modify: `backend/app/ingest/pipeline.py`
- Modify: `backend/app/ingest/rebuild.py`
- Create: `backend/app/rag/structured_retrieval.py`
- Modify: `backend/tests/test_rag_structured_retrieval.py`

**Step 1: Generalize FAISS building beyond chunk-only indexing**

Extend the FAISS helper so it can build named corpora instead of only chunks. Target output structure:

```text
storage/faiss/
  chunks/
  logic_steps/
  claims/
  propositions/
```

Prefer adding a generic builder such as:

```python
def build_faiss_for_rows(rows: list[dict], out_dir: str, *, text_key: str, metadata_keys: list[str]) -> dict:
    ...
```

Keep `build_faiss_for_chunks()` as a compatibility wrapper.

**Step 2: Build all QA corpora during ingest and rebuild**

Update `ingest_markdowns()` and `rebuild_global_faiss()` so they build:
- chunk FAISS
- logic-step FAISS
- claim FAISS
- proposition FAISS

Use the Neo4j helper exporters added in Task 2. If proposition rows are empty, skip that corpus cleanly instead of failing the whole rebuild.

**Step 3: Implement a structured retrieval module**

Create `backend/app/rag/structured_retrieval.py` with functions like:

```python
def retrieve_logic_steps(query: str, k: int, allowed_sources: set[str] | None = None) -> list[dict]: ...
def retrieve_claims(query: str, k: int, allowed_sources: set[str] | None = None) -> list[dict]: ...
def retrieve_propositions(query: str, k: int, allowed_sources: set[str] | None = None) -> list[dict]: ...
```

Use:
- FAISS when the corpus index exists
- lexical fallback when FAISS is missing
- deterministic output fields: `kind`, `id`, `text`, `score`, `paper_source`, `paper_id`, provenance fields

**Step 4: Run the structured retrieval tests**

Run: `pytest backend/tests/test_rag_structured_retrieval.py -q`
Expected: PASS

**Step 5: Commit the multi-corpus retrieval base**

```bash
git add backend/app/vector/faiss_store.py backend/app/ingest/pipeline.py backend/app/ingest/rebuild.py backend/app/rag/structured_retrieval.py backend/tests/test_rag_structured_retrieval.py
git commit -m "feat: add multi-corpus qa retrieval indexes"
```

### Task 4: Introduce the single-call Ask planner for intent recognition and query rewriting

**Files:**
- Create: `backend/app/rag/planner.py`
- Modify: `backend/app/rag/models.py`
- Modify: `backend/app/rag/service.py`
- Modify: `backend/tests/test_rag_planner.py`
- Modify: `backend/tests/test_rag_service.py`

**Step 1: Add planner response models**

Introduce strict Pydantic models for planner output:

```python
class AskIntent(str, Enum):
    paper_detail = "paper_detail"
    foundational = "foundational"
    hybrid_explanation = "hybrid_explanation"
    comparison = "comparison"

class RetrievalPlan(str, Enum):
    paper_first_then_textbook = "paper_first_then_textbook"
    textbook_first_then_paper = "textbook_first_then_paper"
    hybrid_parallel = "hybrid_parallel"
    claim_first = "claim_first"
    proposition_first = "proposition_first"
```

The planner payload must always include `main_query`. The per-corpus query fields are optional and should fall back to `main_query` when omitted.

**Step 2: Implement the planner module**

Add a single LLM planner call that returns:

```python
{
    "intent": "...",
    "retrieval_plan": "...",
    "main_query": "...",
    "paper_query": "...",
    "textbook_query": "...",
    "proposition_query": "...",
    "confidence": 0.0,
    "reason": "..."
}
```

Planner rules:
- it must not answer the user question
- it must only plan retrieval
- on parse failure or timeout, return a deterministic fallback:

```python
{
    "intent": "paper_detail",
    "retrieval_plan": "paper_first_then_textbook",
    "main_query": question,
}
```

**Step 3: Wire the planner into `_prepare_ask_v2_context()`**

Call the planner before retrieval and log the resolved plan into the returned bundle. Do not change the public endpoint name.

**Step 4: Run planner and service tests**

Run: `pytest backend/tests/test_rag_planner.py backend/tests/test_rag_service.py -q`
Expected: PASS

**Step 5: Commit the planner**

```bash
git add backend/app/rag/planner.py backend/app/rag/models.py backend/app/rag/service.py backend/tests/test_rag_planner.py backend/tests/test_rag_service.py
git commit -m "feat: add ask planner for intent and query routing"
```

### Task 5: Rework Ask retrieval to use chunks, logic steps, claims, propositions, and textbooks together

**Files:**
- Modify: `backend/app/rag/service.py`
- Modify: `backend/app/rag/evidence_orchestrator.py`
- Modify: `backend/app/rag/fusion_retrieval.py`
- Modify: `backend/app/rag/models.py`
- Modify: `backend/tests/test_rag_service.py`
- Modify: `backend/tests/test_rag_fusion_retrieval.py`

**Step 1: Add structured evidence models to the Ask response**

Extend the response models with something like:

```python
class StructuredEvidenceItem(BaseModel):
    kind: Literal["logic_step", "claim", "proposition"]
    source_id: str
    text: str
    score: float | None = None
    paper_source: str | None = None
    paper_id: str | None = None
    proposition_id: str | None = None
    source_kind: str | None = None
    source_ref_id: str | None = None
```

Add planner metadata too:
- `intent`
- `retrieval_plan`
- `query_plan`

**Step 2: Implement retrieval-plan branching**

Inside `_prepare_ask_v2_context()`:
- `paper_first_then_textbook`: retrieve chunks + logic/claim first, then textbook + proposition support
- `textbook_first_then_paper`: retrieve textbook fusion/textbook proposition support first, then paper chunks/claims for supplementation
- `hybrid_parallel`: run all channels concurrently and fuse
- `claim_first` / `proposition_first`: oversample those corpora before chunks

Do not remove the current chunk retrieval path. It remains the hard fallback and one of the fused channels.

**Step 3: Fuse heterogeneous evidence deterministically**

Update the merger so it can handle:
- paper text evidence
- structured paper evidence
- textbook/fusion evidence
- proposition evidence

Keep ranking explainable. A simple first pass is:

```python
final_score = 0.40 * retrieval_score + 0.25 * provenance_score + 0.20 * route_priority + 0.15 * grounding_ready
```

Do not let one corpus monopolize the final bundle. Reserve slots per corpus before the final global trim.

**Step 4: Update the prompt payload**

Add distinct sections:
- `Evidence`
- `Structured Evidence`
- `Graph Context`
- `Textbook Fundamentals`

Use planner-chosen query text in retrieval, not directly in answer generation. The user-visible question should remain the original user question.

**Step 5: Run Ask and fusion tests**

Run: `pytest backend/tests/test_rag_service.py backend/tests/test_rag_fusion_retrieval.py -q`
Expected: PASS

**Step 6: Commit the retrieval orchestration**

```bash
git add backend/app/rag/service.py backend/app/rag/evidence_orchestrator.py backend/app/rag/fusion_retrieval.py backend/app/rag/models.py backend/tests/test_rag_service.py backend/tests/test_rag_fusion_retrieval.py
git commit -m "feat: route ask retrieval across structured and textbook evidence"
```

### Task 6: Add sentence-level grounding to the Ask evidence bundle

**Files:**
- Create: `backend/app/rag/grounding.py`
- Modify: `backend/app/rag/service.py`
- Modify: `backend/app/rag/models.py`
- Modify: `backend/tests/test_rag_structured_retrieval.py`
- Modify: `backend/tests/test_rag_service.py`

**Step 1: Add grounding models**

Add a compact grounding item:

```python
class GroundingItem(BaseModel):
    source_kind: str
    source_id: str
    quote: str
    chunk_id: str | None = None
    md_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    textbook_id: str | None = None
    chapter_id: str | None = None
```

**Step 2: Implement grounding resolvers**

Resolver rules:
- `Claim` grounding should prefer the claim's own `evidence_quote` and chunk links
- `LogicStep` grounding should use its `EVIDENCED_BY` chunk chain
- `Proposition` grounding should resolve through source claim or textbook `MAPS_TO` / `EXPLAINS`
- textbook-only grounding should use `evidence_quote` and chapter metadata from fusion/textbook rows

If an item has no sentence-ready quote, include no grounding row rather than inventing one.

**Step 3: Attach grounding to the final Ask bundle**

Grounding should be returned in the API and inserted into the prompt only as compact support, not as verbose duplicated evidence. The prompt must stay bounded.

**Step 4: Run grounding tests**

Run: `pytest backend/tests/test_rag_structured_retrieval.py backend/tests/test_rag_service.py -q`
Expected: PASS

**Step 5: Commit sentence grounding**

```bash
git add backend/app/rag/grounding.py backend/app/rag/service.py backend/app/rag/models.py backend/tests/test_rag_structured_retrieval.py backend/tests/test_rag_service.py
git commit -m "feat: add sentence-level grounding for ask evidence"
```

### Task 7: Update the Ask frontend to render propositions, planner metadata, and grounding details

**Files:**
- Modify: `frontend/src/loaders/ask.ts`
- Modify: `frontend/src/state/types.ts`
- Modify: `frontend/src/panels/AskPanel.tsx`
- Modify: `frontend/src/components/RightPanel.tsx`
- Modify: `frontend/src/components/rightPanelModel.ts`
- Modify: `frontend/tests/askPropositionGraph.test.ts`
- Modify: `frontend/tests/rightPanelAskSummary.test.tsx`

**Step 1: Extend Ask response typing**

Add frontend types for:
- `structured_evidence`
- `grounding`
- `intent`
- `retrieval_plan`
- `query_plan`

Keep all new fields optional so older payloads still render.

**Step 2: Add proposition nodes to the Ask graph builder**

Teach `buildAskGraph()` to render proposition nodes and connect them to:
- claim nodes when provenance is claim-based
- textbook entity nodes when provenance is textbook-based
- logic nodes when the planner or structured evidence says the proposition is method/result scoped

Use a new `kind: 'proposition'`.

**Step 3: Surface planner and grounding metadata in the right panel**

Add compact summaries:
- detected intent
- retrieval plan
- structured evidence counts
- top grounding quotes

Do not overload the chat transcript itself. Keep the detailed metadata in the side panel / evidence list.

**Step 4: Run focused frontend tests**

Run: `npm test -- --run tests/askPropositionGraph.test.ts tests/rightPanelAskSummary.test.tsx`
Expected: PASS

**Step 5: Commit the Ask frontend update**

```bash
git add frontend/src/loaders/ask.ts frontend/src/state/types.ts frontend/src/panels/AskPanel.tsx frontend/src/components/RightPanel.tsx frontend/src/components/rightPanelModel.ts frontend/tests/askPropositionGraph.test.ts frontend/tests/rightPanelAskSummary.test.tsx
git commit -m "feat: render proposition-aware ask evidence"
```

### Task 8: End-to-end verification and regression guardrails

**Files:**
- No additional file changes expected

**Step 1: Run focused backend QA tests**

Run:

```bash
pytest backend/tests/test_rag_planner.py backend/tests/test_rag_structured_retrieval.py backend/tests/test_rag_service.py backend/tests/test_rag_fusion_retrieval.py backend/tests/test_fusion_query_metadata.py -q
```

Expected: PASS

**Step 2: Run focused frontend Ask tests**

Run:

```bash
npm test -- --run tests/askPropositionGraph.test.ts tests/rightPanelAskSummary.test.tsx tests/askFusionGraph.test.ts
```

Expected: PASS

**Step 3: Run a backend smoke rebuild if local services are available**

Run:

```bash
pytest backend/tests/test_embedding.py -q
```

Then manually verify that `/tasks/rebuild/faiss` still succeeds after the multi-corpus FAISS changes.

**Step 4: Run the production frontend build**

Run:

```bash
cd frontend
npm run build
```

Expected: PASS

**Step 5: Manual smoke-check scenarios**

Verify all of these from the Ask UI or API:
- a paper-detail question returns chunk + claim/logic support from the paper
- a foundational question returns textbook/proposition evidence first, then paper supplementation when available
- a hybrid explanation question returns both paper and textbook evidence with `dual_evidence_coverage = true`
- planner failure gracefully falls back to legacy paper-first Ask
- grounding rows point to real quotes rather than generated summaries

**Step 6: Commit the verification checkpoint**

```bash
git add -A
git commit -m "chore: verify proposition-aware qa router upgrade"
```
