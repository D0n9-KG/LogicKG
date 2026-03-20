# Overview Community-Only 3D Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the overview 3D scene show all global communities as the primary graph while preserving a moderate amount of cross-community structure and good frame-rate.

**Architecture:** Keep the change local-only for now. Update the backend community overview graph builder to support a community-only mode with sparse-but-visible `similar` edges, then update the frontend loader defaults to request that mode. Tighten the 3D seed layout for all-community scenes so the graph reads as a dense overview instead of scattered islands.

**Tech Stack:** FastAPI, Neo4j-backed community API, React, Vite, Vitest, pytest, Three.js / 3d-force-graph

---

## Chunk 1: Lock Behavior With Tests

### Task 1: Backend community-only overview graph tests

**Files:**
- Modify: `backend/tests/test_community_overview_graph.py`

- [ ] Add a failing unit test that requests `include_members=False` and asserts the graph contains only community nodes plus a bounded set of `similar` edges.
- [ ] Add a failing endpoint test that verifies `/community/overview-graph` accepts `include_members=false` and can return more than the old 80-community cap.
- [ ] Run the targeted backend tests and confirm the new assertions fail for the expected reason.

### Task 2: Frontend overview loader and 3D layout tests

**Files:**
- Modify: `frontend/tests/overviewCommunity3dLoader.test.ts`
- Modify: `frontend/tests/graph3dModel.test.ts`

- [ ] Add a failing loader test that expects the overview 3D request to use the community-only mode and larger all-community limits.
- [ ] Add a failing layout test that asserts an all-community scene seeds into a compact radius instead of the current wide orbit.
- [ ] Run the targeted frontend tests and confirm they fail for the intended missing behavior.

## Chunk 2: Implement Community-Only Overview 3D

### Task 3: Backend graph builder and route

**Files:**
- Modify: `backend/app/community/overview_graph.py`
- Modify: `backend/app/api/routers/community.py`

- [ ] Add an `include_members` flag to the overview builder and route.
- [ ] Allow larger `community_limit` values for the community-only mode while keeping `max_nodes`/`max_edges` bounded.
- [ ] In community-only mode, emit only community nodes and `similar` edges, but keep similarity scoring rich enough to avoid an empty-looking graph.

### Task 4: Frontend loader defaults

**Files:**
- Modify: `frontend/src/loaders/overview.ts`

- [ ] Update the overview 3D defaults to request the all-community mode.
- [ ] Keep community edges visually present but bounded to a moderate count.
- [ ] Preserve existing caching and invalidation behavior.

### Task 5: Community-only 3D seed layout

**Files:**
- Modify: `frontend/src/components/graph3dModel.ts`

- [ ] Add a compact seed layout path for scenes made entirely of community nodes.
- [ ] Keep the resulting spread visually full without pushing clusters off-screen.

## Chunk 3: Verify

### Task 6: Focused verification

**Files:**
- No new files

- [ ] Run `pytest -q backend/tests/test_community_overview_graph.py`
- [ ] Run `npm run test -- overviewCommunity3dLoader.test.ts graph3dModel.test.ts`
- [ ] Run `npm run lint`
- [ ] Run `npm run build`
