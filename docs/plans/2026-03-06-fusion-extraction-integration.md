# Fusion Extraction Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract the low-risk, high-value Fusion backend capabilities from `feature/fusion-one-shot-rebuild` into `main` without regressing the current discovery/config-center/ask_v2 mainline.

**Architecture:** Keep the current `main` shell and page structure intact. Add Fusion as an additive backend capability: a dedicated Fusion router/service layer, a rebuild task, Neo4j query/write helpers, and optional ask_v2 response enrichment using textbook fundamentals. Do not import the worktree’s routing rollback or old page architecture.

**Tech Stack:** FastAPI, Neo4j Python driver, existing task manager, existing ask_v2 service, pytest, Vitest (regression only).

---

### Task 1: Lock Fusion retrieval behavior with tests

**Files:**
- Create: `backend/tests/test_fusion_router.py`
- Create: `backend/tests/test_fusion_graph_contract.py`
- Create: `backend/tests/test_rag_fusion_retrieval.py`
- Modify: `backend/tests/test_rag_models_contract.py`

**Step 1: Write the failing tests**

- Add router tests for `/fusion/rebuild`, `/fusion/graph`, and DOI-safe query endpoints.
- Add contract tests for fusion graph filtering and ranking helpers.
- Extend RAG model contract tests to assert optional `fusion_evidence` and `dual_evidence_coverage`.

**Step 2: Run tests to verify they fail**

Run: `cd backend && .\\.venv\\Scripts\\python.exe -m pytest tests/test_fusion_router.py tests/test_fusion_graph_contract.py tests/test_rag_fusion_retrieval.py tests/test_rag_models_contract.py -q`

Expected: FAIL because the Fusion router/service/retrieval modules do not exist yet in `main`.

### Task 2: Add Fusion backend primitives

**Files:**
- Create: `backend/app/fusion/__init__.py`
- Create: `backend/app/fusion/builder.py`
- Create: `backend/app/fusion/community.py`
- Create: `backend/app/fusion/keywords.py`
- Create: `backend/app/fusion/linking.py`
- Create: `backend/app/fusion/service.py`
- Create: `backend/app/rag/fusion_retrieval.py`

**Step 1: Add minimal production code**

- Copy only the Fusion primitives needed by the service layer.
- Exclude speculative schema-evolution helpers that are not required by the extracted integration.

**Step 2: Re-run the focused tests**

Run: `cd backend && .\\.venv\\Scripts\\python.exe -m pytest tests/test_rag_fusion_retrieval.py tests/test_rag_models_contract.py -q`

Expected: partial progress; router/service tests still fail until API wiring is added.

### Task 3: Wire Fusion into backend APIs and tasks

**Files:**
- Create: `backend/app/api/routers/fusion.py`
- Modify: `backend/app/graph/neo4j_client.py`
- Modify: `backend/app/tasks/models.py`
- Modify: `backend/app/tasks/handlers.py`
- Modify: `backend/app/api/routers/tasks.py`
- Modify: `backend/app/main.py`

**Step 1: Add the failing integration surface**

- Add `TaskType.rebuild_fusion`
- Register `handle_rebuild_fusion`
- Add `/tasks/rebuild/fusion`
- Add `/fusion/*` router
- Add the Neo4j helpers required by Fusion service and query endpoints

**Step 2: Run the focused backend suite**

Run: `cd backend && .\\.venv\\Scripts\\python.exe -m pytest tests/test_fusion_router.py tests/test_fusion_graph_contract.py tests/test_rag_fusion_retrieval.py tests/test_rag_models_contract.py -q`

Expected: PASS.

### Task 4: Enrich ask_v2 without regressing the current UI contract

**Files:**
- Modify: `backend/app/rag/models.py`
- Modify: `backend/app/rag/service.py`

**Step 1: Add optional response fields**

- Add `fusion_evidence` and `dual_evidence_coverage` as optional additive fields.
- Keep `retrieval_mode`, `structured_knowledge`, and current ask_v2 semantics unchanged.

**Step 2: Use Fusion evidence opportunistically**

- If Fusion basics exist for retrieved paper sources, inject them into the prompt and response.
- If Fusion has not been rebuilt yet, degrade gracefully to current behavior.

**Step 3: Run the focused backend suite again**

Run: `cd backend && .\\.venv\\Scripts\\python.exe -m pytest tests/test_fusion_router.py tests/test_fusion_graph_contract.py tests/test_rag_fusion_retrieval.py tests/test_rag_models_contract.py tests/test_rag_service.py tests/test_rag_ask_v2_api.py -q`

Expected: PASS.

### Task 5: Regression validation

**Files:**
- Verify only

**Step 1: Run backend regression**

Run: `cd backend && .\\.venv\\Scripts\\python.exe -m pytest -q`

Expected: PASS.

**Step 2: Run frontend regression**

Run: `cd frontend && npm test && npm run build && npm run lint`

Expected: PASS.

### Task 6: Clean the old worktree

**Files:**
- Remove worktree: `.worktrees/feature-fusion-one-shot-rebuild` (actual path `.worktrees/fusion-one-shot-rebuild`)
- Delete branch: `feature/fusion-one-shot-rebuild`

**Step 1: Verify extracted value is integrated**

- Confirm targeted backend tests and full regression pass on `main`.

**Step 2: Remove the stale worktree and branch**

Run: `git worktree remove --force .worktrees/fusion-one-shot-rebuild && git branch -D feature/fusion-one-shot-rebuild`

Expected: old exploratory branch state is removed locally after successful extraction.
