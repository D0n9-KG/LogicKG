# Ask Session Delete + Multi-turn QA Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add visible ask-session history deletion in the QA panel and make follow-up questions send recent conversation context to the backend so multi-turn QA works end to end.

**Architecture:** Keep the existing client-side multi-session store as the source of truth for session history, expose session switching/deletion in the left ask panel, and derive a compact conversation payload from the active session when submitting a new turn. Extend `/rag/ask_v2` and `/rag/ask_v2_stream` to accept prior turns, then inject that context into retrieval planning and final LLM prompting without changing the existing answer/evidence response contract.

**Tech Stack:** React 19, TypeScript, Vitest, FastAPI, Pydantic, Python service-layer prompt assembly

---

### Task 1: Lock frontend multi-turn request behavior with tests

**Files:**
- Modify: `frontend/tests/askPanelModel.test.ts`
- Modify: `frontend/src/panels/askPanelModel.ts`

**Step 1: Write the failing test**

Add a test that builds a request conversation payload from prior ask turns and asserts:
- only completed/error/running turns with meaningful content are included
- ordering is oldest to newest
- the current draft question is not duplicated into history
- the payload is capped to a small recent-window size

**Step 2: Run test to verify it fails**

Run: `npm test -- askPanelModel.test.ts`
Expected: FAIL because the helper does not exist yet.

**Step 3: Write minimal implementation**

Add a pure helper in `frontend/src/panels/askPanelModel.ts` to serialize recent turns into a backend-friendly conversation array.

**Step 4: Run test to verify it passes**

Run: `npm test -- askPanelModel.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/tests/askPanelModel.test.ts frontend/src/panels/askPanelModel.ts
git commit -m "test: cover ask multi-turn request payload"
```

### Task 2: Lock backend conversation-context prompting with tests

**Files:**
- Modify: `backend/tests/test_rag_service.py`
- Modify: `backend/tests/test_rag_ask_v2_api.py`
- Modify: `backend/app/rag/models.py`
- Modify: `backend/app/api/routers/rag.py`
- Modify: `backend/app/rag/service.py`

**Step 1: Write the failing test**

Add backend tests that assert:
- `AskV2Request` accepts a `conversation` array
- `_prepare_ask_v2_context(...)` places prior turns into the assembled user prompt before the current question
- `ask_v2(...)` and `ask_v2_stream(...)` pass the conversation through unchanged

**Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_rag_service.py -k conversation -q`
Expected: FAIL because the request model and service signature do not support conversation yet.

**Step 3: Write minimal implementation**

Extend the Pydantic request model with a compact conversation schema and thread it through router/service helpers. Add a formatter that injects recent history into the user prompt in a bounded form.

**Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_rag_service.py -k conversation -q`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/tests/test_rag_service.py backend/tests/test_rag_ask_v2_api.py backend/app/rag/models.py backend/app/api/routers/rag.py backend/app/rag/service.py
git commit -m "test: cover ask conversation context"
```

### Task 3: Wire frontend submit flow and session history UI

**Files:**
- Modify: `frontend/src/panels/AskPanel.tsx`
- Modify: `frontend/src/panels/askPanelModel.ts`
- Modify: `frontend/src/components/RightPanel.tsx`
- Modify: `frontend/tests/rightPanelAskSummary.test.tsx`

**Step 1: Write the failing test**

Add or adjust tests so the ask summary path still works with the new `ask.sessions/currentSessionId` state shape and session-derived current turn selection.

**Step 2: Run test to verify it fails**

Run: `npm test -- rightPanelAskSummary.test.tsx`
Expected: FAIL if the old test state shape no longer matches the ask store contract.

**Step 3: Write minimal implementation**

In `AskPanel.tsx`:
- render a session list above or beside the conversation stream
- show session title, preview, timestamp, turn count, active state
- add switch and delete controls
- include recent conversation payload in both streaming and fallback POST bodies

In `RightPanel.tsx`:
- read the active ask session from the new store shape consistently

**Step 4: Run test to verify it passes**

Run: `npm test -- rightPanelAskSummary.test.tsx askSessions.test.ts askPanelModel.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/panels/AskPanel.tsx frontend/src/panels/askPanelModel.ts frontend/src/components/RightPanel.tsx frontend/tests/rightPanelAskSummary.test.tsx frontend/tests/askSessions.test.ts frontend/tests/askPanelModel.test.ts
git commit -m "feat: add ask session history controls"
```

### Task 4: Full verification

**Files:**
- Modify: none unless fixes are required

**Step 1: Run frontend verification**

Run: `npm test -- askSessions.test.ts askPanelModel.test.ts rightPanelAskSummary.test.tsx`
Expected: PASS

**Step 2: Run backend verification**

Run: `pytest backend/tests/test_rag_ask_v2_api.py backend/tests/test_rag_service.py -q`
Expected: PASS

**Step 3: Run build verification**

Run: `npm run build`
Expected: PASS

**Step 4: Commit**

```bash
git add -A
git commit -m "feat: support ask history deletion and multi-turn qa"
```
