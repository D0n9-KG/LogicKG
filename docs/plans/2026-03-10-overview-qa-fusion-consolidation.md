# Overview And QA Fusion Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the standalone fusion frontend, strengthen Ask with fusion-backed textbook evidence, and upgrade the overview 3D graph so textbook structures render as readable clusters.

**Architecture:** Keep fusion as a backend capability and retrieval layer, but move its user-facing value into Ask. Extend the overview graph contract to emit mixed graph entities for papers and textbooks, then teach the frontend loader and 3D renderer to preserve textbook-community structure.

**Tech Stack:** FastAPI, Neo4j client helpers, React, TypeScript, Vitest, Pytest, 3d-force-graph

---

### Task 1: Lock the desired contracts in tests

**Files:**
- Create: `backend/tests/test_overview_graph_contract.py`
- Modify: `backend/tests/test_rag_service.py`
- Modify: `frontend/tests/overviewLoader.test.ts`
- Create: `frontend/tests/askFusionGraph.test.ts`

**Step 1: Write the failing backend overview graph test**

Add a test asserting `/graph/network`-style payloads can contain `textbook`, `chapter`, and `community` nodes plus their connector edges.

**Step 2: Run the backend overview test to verify it fails**

Run: `pytest backend/tests/test_overview_graph_contract.py -q`
Expected: FAIL because the current overview graph only returns paper citation nodes.

**Step 3: Write the failing Ask fusion test**

Add/extend tests asserting `_prepare_ask_v2_context()` returns fusion evidence with textbook metadata and that the frontend Ask graph builder maps fusion rows into textbook/chapter/entity nodes.

**Step 4: Run Ask-related tests to verify they fail**

Run: `pytest backend/tests/test_rag_service.py -q`
Run: `npm test -- --run tests/askFusionGraph.test.ts tests/overviewLoader.test.ts`
Expected: FAIL because the Ask frontend state and overview loader do not yet expose these structures.

### Task 2: Extend the overview graph backend for textbook clustering

**Files:**
- Modify: `backend/app/graph/neo4j_client.py`
- Modify: `backend/app/api/routers/graph.py` (only if request params need widening)

**Step 1: Implement a mixed overview graph query**

Return papers as before, then add textbook, chapter, and community anchor nodes plus edges such as `has_chapter`, `has_community`, and `community_member`.

**Step 2: Keep node counts bounded**

Use deterministic sampling so the overview graph stays readable and does not explode in size.

**Step 3: Run backend overview tests**

Run: `pytest backend/tests/test_overview_graph_contract.py -q`
Expected: PASS

### Task 3: Teach the frontend overview loader and 3D renderer about textbook communities

**Files:**
- Modify: `frontend/src/loaders/overview.ts`
- Modify: `frontend/src/components/Graph3D.tsx`
- Modify: `frontend/src/state/types.ts` (only if extra node metadata is needed)

**Step 1: Map the new overview payload into graph elements**

Preserve node kinds like `textbook`, `chapter`, and `community` and attach lightweight grouping metadata for layout hints.

**Step 2: Update the 3D node styling and force behavior**

Give textbook anchors and communities distinct geometry/color/size, and bias chapter/community nodes into visible clusters without breaking existing paper graphs.

**Step 3: Run frontend overview tests**

Run: `npm test -- --run tests/overviewLoader.test.ts tests/graph3dModel.test.ts`
Expected: PASS

### Task 4: Remove the standalone fusion frontend and move value into Ask

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/TopBar.tsx`
- Modify: `frontend/src/components/StatusBar.tsx`
- Modify: `frontend/src/loaders/ask.ts`
- Modify: `frontend/src/state/types.ts`
- Modify: `frontend/src/panels/AskPanel.tsx`
- Modify: `frontend/src/components/RightPanel.tsx`

**Step 1: Redirect `/fusion` to `/ask` and remove fusion nav affordances**

Keep the backend APIs untouched.

**Step 2: Add fusion evidence to Ask response typing and UI state**

Surface textbook fundamentals, dual-evidence coverage, and source chapter information in the Ask graph and right-side evidence detail.

**Step 3: Run focused frontend tests**

Run: `npm test -- --run tests/askFusionGraph.test.ts`
Expected: PASS

### Task 5: End-to-end verification

**Files:**
- No additional file changes expected

**Step 1: Run focused backend tests**

Run: `pytest backend/tests/test_overview_graph_contract.py backend/tests/test_rag_service.py -q`

**Step 2: Run focused frontend tests**

Run: `npm test -- --run tests/overviewLoader.test.ts tests/askFusionGraph.test.ts tests/graph3dModel.test.ts`

**Step 3: Run production build**

Run: `npm run build`

**Step 4: Smoke-check the app**

Verify:
- `/fusion` redirects into Ask
- Ask shows fusion-backed textbook evidence
- Overview 3D displays textbook communities as visible clusters
