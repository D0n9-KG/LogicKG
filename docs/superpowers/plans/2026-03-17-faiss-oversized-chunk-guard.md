# FAISS Oversized Chunk Guard Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep FAISS rebuilds from failing when a small number of markdown chunks exceed the embedding model context window.

**Architecture:** Add a FAISS-only text segmentation layer in the vector-store builder so existing Neo4j chunks, `chunk_id` references, and extraction artifacts remain unchanged. Then add retrieval-side dedup guards so multiple FAISS segments derived from one source row collapse back to the original logical hit.

**Tech Stack:** Python, FastAPI backend utilities, LangChain FAISS wrapper, pytest

---

## Chunk 1: Test-First Guard Rails

### Task 1: Lock the oversized-row behavior with tests

**Files:**
- Create: `backend/tests/test_faiss_store_segmentation.py`
- Test: `backend/tests/test_faiss_store_segmentation.py`

- [ ] **Step 1: Write the failing test**

Add tests that prove:
- oversized FAISS rows are split into multiple indexed texts before embedding
- split rows keep the original logical identifier in metadata
- rows under the threshold are left unchanged

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_faiss_store_segmentation.py`
Expected: FAIL because the segmentation helper does not exist yet

### Task 2: Lock the retrieval dedup behavior with tests

**Files:**
- Modify: `backend/tests/test_rag_service.py`
- Modify: `backend/tests/test_rag_structured_retrieval.py`

- [ ] **Step 1: Write the failing test**

Add tests that prove:
- FAISS-only chunk retrieval collapses duplicate `chunk_id` hits while preserving order
- structured retrieval collapses duplicate `source_id` or `id` hits returned from FAISS

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_rag_service.py tests/test_rag_structured_retrieval.py`
Expected: FAIL because duplicate FAISS rows are currently returned directly

## Chunk 2: Minimal Implementation

### Task 3: Add FAISS-only segmentation

**Files:**
- Modify: `backend/app/vector/faiss_store.py`
- Test: `backend/tests/test_faiss_store_segmentation.py`

- [ ] **Step 1: Write minimal implementation**

Add a helper that:
- splits only oversized texts
- prefers soft boundaries when present and falls back to hard character slicing
- preserves the original metadata and records optional segment metadata for debugging

- [ ] **Step 2: Run focused tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_faiss_store_segmentation.py`
Expected: PASS

### Task 4: Add retrieval dedup safeguards

**Files:**
- Modify: `backend/app/rag/service.py`
- Modify: `backend/app/rag/structured_retrieval.py`
- Test: `backend/tests/test_rag_service.py`
- Test: `backend/tests/test_rag_structured_retrieval.py`

- [ ] **Step 1: Write minimal implementation**

Ensure:
- FAISS-only evidence merging deduplicates repeated `chunk_id` hits
- structured FAISS retrieval deduplicates repeated logical rows by `source_id`, `id`, or `chunk_id`

- [ ] **Step 2: Run focused tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_rag_service.py tests/test_rag_structured_retrieval.py`
Expected: PASS

## Chunk 3: Verification

### Task 5: Re-run targeted rebuild-adjacent checks

**Files:**
- Test: `backend/tests/test_rebuild_cleanup.py`

- [ ] **Step 1: Run regression checks**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_faiss_store_segmentation.py tests/test_rag_service.py tests/test_rag_structured_retrieval.py tests/test_rebuild_cleanup.py`
Expected: PASS

- [ ] **Step 2: Summarize operational follow-up**

Document that the next server-side action is a read-only-safe retry of FAISS rebuild after deployment, with no need to reparse or rewrite existing chunks.
