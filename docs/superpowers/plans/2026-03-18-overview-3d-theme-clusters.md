# Overview 3D Theme Cluster Styling Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the overview 3D community graph a more refined research-grade look by coloring communities according to topic clusters instead of rendering the whole scene in a single hue.

**Architecture:** Keep the change local-only and mostly frontend-scoped. Extend the overview community loader to retain community keywords, derive stable theme-cluster assignments from the visible communities' keyword overlap, and apply a restrained palette to community nodes, glows, and strong `similar` edges while leaving background structure neutral.

**Tech Stack:** React, TypeScript, Vitest, Three.js, 3d-force-graph

---

## Chunk 1: Lock Behavior With Tests

### Task 1: Loader keyword mapping

**Files:**
- Modify: `frontend/tests/overviewCommunity3dLoader.test.ts`

- [ ] Add a failing test that verifies overview 3D community nodes retain the backend `keywords` array in frontend graph data.
- [ ] Run `npm run test -- overviewCommunity3dLoader.test.ts` and confirm the new assertion fails for the expected missing field.

### Task 2: Theme cluster assignment and palette behavior

**Files:**
- Create: `frontend/tests/graph3dTheme.test.ts`

- [ ] Add a failing test that verifies communities with overlapping keywords land in the same theme cluster.
- [ ] Add a failing test that verifies unrelated keyword groups receive different palette clusters.
- [ ] Add a failing test that verifies only community nodes are recolored while non-community nodes keep their existing semantic colors.
- [ ] Run `npm run test -- graph3dTheme.test.ts` and confirm the tests fail for the intended missing behavior.

## Chunk 2: Implement Theme Cluster Styling

### Task 3: Theme helper

**Files:**
- Create: `frontend/src/components/graph3dTheme.ts`

- [ ] Implement stable keyword normalization and overlap-based topic clustering for visible community nodes.
- [ ] Map theme clusters onto a restrained research-grade palette.
- [ ] Expose helpers for community node colors and strong-edge highlight colors.

### Task 4: Connect loader data to renderer

**Files:**
- Modify: `frontend/src/state/types.ts`
- Modify: `frontend/src/loaders/overview.ts`
- Modify: `frontend/src/components/Graph3D.tsx`

- [ ] Add community keywords to the shared graph node type.
- [ ] Preserve overview community keywords in the loader.
- [ ] Apply theme-cluster styling to community node spheres, auras, rings, and highlighted `similar` edges without making the scene gaudy.

## Chunk 3: Verify

### Task 5: Focused verification

**Files:**
- No new files

- [ ] Run `npm run test -- overviewCommunity3dLoader.test.ts graph3dTheme.test.ts graph3dLinkBudget.test.ts graph3dModel.test.ts graphCanvasRuntime.test.tsx`
- [ ] Run `npm run lint`
- [ ] Run `npm run build`
