# Overview 3D Edge Declutter Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the visual clutter in the overview 3D community graph while keeping the network feeling connected and revealing the selected community's full loaded relationships.

**Architecture:** Keep the backend community overview payload unchanged for now and move the decluttering into the frontend 3D display layer. Compute a default "skeleton" subset of `similar` edges for the overview scene, preserve all non-similar edges, and reintroduce every loaded `similar` edge incident to the selected community. Tone down the styling of background `similar` edges so the graph stays readable at a glance.

**Tech Stack:** React, TypeScript, 3d-force-graph, Three.js, Vitest

---

## Chunk 1: Lock Behavior With Tests

### Task 1: Similar-edge budgeting tests

**Files:**
- Create: `frontend/tests/graph3dLinkBudget.test.ts`

- [ ] Write a failing test that verifies the default overview 3D link set keeps a bounded skeleton of `similar` edges instead of all of them.
- [ ] Write a failing test that verifies selecting a community restores all loaded `similar` edges incident to that community.
- [ ] Write a failing test that verifies non-`similar` edges are always preserved.
- [ ] Run `npm run test -- graph3dLinkBudget.test.ts` and confirm the tests fail for the expected missing behavior.

## Chunk 2: Implement Frontend Decluttering

### Task 2: Extract link-budget helper

**Files:**
- Create: `frontend/src/components/graph3dLinkBudget.ts`

- [ ] Implement a deterministic helper that computes the default skeleton subset for `similar` edges.
- [ ] Ensure the helper unions in all loaded incident `similar` edges for the selected community node.
- [ ] Annotate links with enough metadata for styling emphasis in the renderer.

### Task 3: Apply the helper in Graph3D

**Files:**
- Modify: `frontend/src/components/Graph3D.tsx`
- Modify: `frontend/src/components/GraphCanvas.tsx`

- [ ] Pass the currently selected node id into `Graph3D`.
- [ ] Use the link-budget helper to feed only the intended overview links into `ForceGraph3D`.
- [ ] Lower the visual weight of background `similar` edges and remove their directional particles.
- [ ] Keep selected-community incident edges brighter so the expansion is visible.

## Chunk 3: Verify

### Task 4: Focused verification

**Files:**
- No new files

- [ ] Run `npm run test -- graph3dLinkBudget.test.ts graph3dModel.test.ts overviewCommunity3dLoader.test.ts graphCanvasRuntime.test.tsx`
- [ ] Run `npm run lint`
- [ ] Run `npm run build`
