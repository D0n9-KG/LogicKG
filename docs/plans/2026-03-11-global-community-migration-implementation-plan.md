# Global Community Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove proposition/evolution as core architecture, introduce `GlobalCommunity`/`GlobalKeyword` as the new shared structure layer, and adapt textbook ingest, Ask, and discovery to community-first behavior.

**Architecture:** Keep Tencent Youtu-GraphRAG responsible for extraction only, then rebuild a whole-graph community layer locally inside LogicKG using a local TreeComm-compatible adapter over `KnowledgeEntity + Claim + LogicStep`. Replace proposition-driven retrieval and discovery with community-driven retrieval and community-driven evidence expansion, then delete proposition/evolution code paths and UI.

**Tech Stack:** FastAPI, Neo4j, NetworkX, sentence-transformers-compatible TreeComm adapter, React, TypeScript, Vitest, Pytest

---

## External Prerequisite: Patch Youtu To Skip Level 4

This repository does not contain the remote `youtu-graphrag` code, but the migration depends on an upstream extraction-only mode.

### External Task P1: Add an extraction-only switch in Youtu

**Files:**
- Modify: `youtu-graphrag/models/constructor/kt_gen.py`
- Modify: `youtu-graphrag/config/base_config.yaml`
- Verify: extraction-only run in the remote environment used by `autoyoutu`

**Step 1: Add a config flag for TreeComm execution**

Add a boolean config like:

```yaml
tree_comm:
  enabled: true
```

**Step 2: Guard `process_level4()` in `KTBuilder.process_all_documents()`**

Use a minimal conditional:

```python
self.triple_deduplicate()
if getattr(self.config.tree_comm, "enabled", True):
    self.process_level4()
```

**Step 3: Run one extraction-only smoke test**

Run the remote build command with TreeComm disabled.

Expected:
- graph JSON still contains extracted nodes/edges
- no community or keyword super-node output is required by LogicKG

**Step 4: Commit upstream change**

```bash
git add models/constructor/kt_gen.py config/base_config.yaml
git commit -m "feat: allow extraction without tree comm"
```

### External Task P2: Align `autoyoutu` with extraction-only mode

**Files:**
- Modify: `<AUTOYOUTU_DIR>/integrated_pipeline.py` or the equivalent config injection point
- Verify: `backend/app/ingest/textbook_pipeline.py` consumes graph output without relying on remote communities

**Step 1: Pass the TreeComm disable flag into the remote Youtu run**

Prefer config or environment-based injection over hard-coded behavior.

**Step 2: Run one chapter through the full remote pipeline**

Expected:
- textbook chapter extraction still succeeds
- downloaded graph JSON is importable by LogicKG

**Step 3: Commit upstream change**

```bash
git add integrated_pipeline.py
git commit -m "feat: run youtu in extraction-only mode"
```

---

### Task 1: Lock the new community-first contracts in tests

**Files:**
- Create: `backend/tests/test_global_community_projection.py`
- Create: `backend/tests/test_global_community_service.py`
- Modify: `backend/tests/test_rag_structured_retrieval.py`
- Modify: `backend/tests/test_discovery_gap_detector.py`
- Modify: `backend/tests/test_textbook_graph_api.py`
- Create: `frontend/tests/askCommunityGraph.test.ts`
- Modify: `frontend/tests/askLoader.test.ts`

**Step 1: Write the failing global community projection test**

Assert the projection builder emits only `KnowledgeEntity`, `Claim`, and `LogicStep` nodes plus approved source-internal edges.

**Step 2: Write the failing community persistence test**

Assert rebuilding communities writes:
- `GlobalCommunity`
- `GlobalKeyword`
- `IN_GLOBAL_COMMUNITY`
- `HAS_GLOBAL_KEYWORD`

**Step 3: Write the failing Ask retrieval contract test**

Assert structured retrieval exposes a `communities` corpus and Ask can expand a `community_id` into member-backed evidence rows.

Example assertion shape:

```python
assert row["kind"] == "community"
assert row["community_id"] == "gc:demo"
assert row["member_ids"] == ["claim:1", "ke:1"]
```

**Step 4: Write the failing discovery contract test**

Assert gaps carry `source_community_ids` instead of `source_proposition_ids`.

**Step 5: Run the failing backend tests**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_global_community_projection.py `
  tests/test_global_community_service.py `
  tests/test_rag_structured_retrieval.py `
  tests/test_discovery_gap_detector.py `
  tests/test_textbook_graph_api.py
```

Expected: FAIL because the codebase has no global community layer yet.

**Step 6: Write the failing frontend Ask community graph test**

Assert the Ask graph renders:
- a `community` node
- member nodes
- evidence links below the member nodes

**Step 7: Run the failing frontend tests**

Run:

```powershell
cd frontend
npm run test -- --run tests/askCommunityGraph.test.ts tests/askLoader.test.ts
```

Expected: FAIL because the frontend still expects proposition-based structure.

**Step 8: Commit**

```bash
git add backend/tests/test_global_community_projection.py backend/tests/test_global_community_service.py backend/tests/test_rag_structured_retrieval.py backend/tests/test_discovery_gap_detector.py backend/tests/test_textbook_graph_api.py frontend/tests/askCommunityGraph.test.ts frontend/tests/askLoader.test.ts
git commit -m "test: lock community first migration contracts"
```

### Task 2: Add local global community schema and persistence primitives

**Files:**
- Modify: `backend/app/graph/neo4j_client.py`
- Modify: `backend/app/settings.py`
- Create: `backend/tests/test_global_community_service.py` (implementation assertions)

**Step 1: Add Neo4j schema support**

Create constraints and indexes for:
- `GlobalCommunity.community_id`
- `GlobalKeyword.keyword_id`

**Step 2: Add community writer helpers**

Implement minimal helpers such as:

```python
def clear_global_communities(self) -> dict[str, int]: ...
def upsert_global_communities(self, items: list[dict]) -> int: ...
def upsert_global_keywords(self, items: list[dict]) -> int: ...
def replace_global_memberships(self, items: list[dict]) -> int: ...
def list_global_community_rows(self, limit: int = 50000) -> list[dict]: ...
def list_global_community_members(self, community_id: str, limit: int = 200) -> list[dict]: ...
```

**Step 3: Add config defaults**

Introduce community rebuild settings for:
- version label
- node and edge limits
- top keywords per community

**Step 4: Run the community service backend tests**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_global_community_service.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/graph/neo4j_client.py backend/app/settings.py backend/tests/test_global_community_service.py
git commit -m "feat: add global community persistence primitives"
```

### Task 3: Vendor the local TreeComm adapter and graph projection builder

**Files:**
- Create: `backend/app/community/__init__.py`
- Create: `backend/app/community/tree_comm_adapter.py`
- Create: `backend/app/community/projection.py`
- Create: `backend/app/community/service.py`
- Create: `backend/tests/test_global_community_projection.py`

**Step 1: Add a thin TreeComm adapter**

Adapt the Youtu algorithm into a local module that accepts a `networkx.MultiDiGraph` and returns:

```python
{
    "communities": [...],
    "keywords": [...],
}
```

Keep the local adapter behavior close to Youtu:
- use node `properties.name`
- use edge `relation`
- preserve semantic plus structural similarity

**Step 2: Build the whole-graph projection**

Implement a projection function that loads:
- textbook `KnowledgeEntity`
- paper `Claim`
- paper `LogicStep`
- source-internal edges only

**Step 3: Build the rebuild service**

Implement a high-level service like:

```python
def rebuild_global_communities(*, progress=None, log=None) -> dict[str, Any]:
    graph = build_global_projection(...)
    result = run_tree_comm(graph, ...)
    write_result_to_neo4j(...)
    return summary
```

**Step 4: Run focused backend tests**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_global_community_projection.py tests/test_global_community_service.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/community backend/tests/test_global_community_projection.py backend/tests/test_global_community_service.py
git commit -m "feat: add local global community rebuild pipeline"
```

### Task 4: Add rebuild tasks and community APIs

**Files:**
- Modify: `backend/app/tasks/models.py`
- Modify: `backend/app/tasks/handlers.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/routers/tasks.py`
- Create: `backend/app/api/routers/community.py`
- Modify: `backend/tests/test_app_main.py`

**Step 1: Add a new task type**

Introduce `rebuild_global_communities`.

**Step 2: Add the task handler**

Delegate to `rebuild_global_communities()` and emit progress stages like:
- `community:init`
- `community:projection`
- `community:cluster`
- `community:write`

**Step 3: Add community APIs**

Expose read endpoints such as:
- `GET /community/list`
- `GET /community/{community_id}`
- `POST /tasks/rebuild/community`

**Step 4: Register the router and task**

Update FastAPI router wiring and task registration.

**Step 5: Run focused tests**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_app_main.py tests/test_global_community_service.py
```

Expected: PASS

**Step 6: Commit**

```bash
git add backend/app/tasks/models.py backend/app/tasks/handlers.py backend/app/main.py backend/app/api/routers/tasks.py backend/app/api/routers/community.py backend/tests/test_app_main.py
git commit -m "feat: expose global community rebuild and read apis"
```

### Task 5: Switch textbook ingest from proposition mapping to community rebuild

**Files:**
- Modify: `backend/app/ingest/textbook_pipeline.py`
- Modify: `backend/app/api/routers/textbooks.py`
- Delete: `backend/app/ingest/textbook_proposition_mapper.py`
- Modify: `backend/tests/test_textbook_graph_api.py`
- Delete: `backend/tests/test_textbook_proposition_mapping.py`

**Step 1: Remove textbook proposition mapping from ingest**

Delete the final `map_entities_to_propositions()` call from textbook ingest.

**Step 2: Trigger or schedule community rebuild after textbook import**

Prefer calling the local community rebuild task rather than doing proposition linking.

**Step 3: Repurpose `/textbooks/fusion/link`**

Replace it with an explicit community rebuild endpoint, or remove it if unused and add a clearer community action.

**Step 4: Run textbook-focused tests**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_textbook_graph_api.py tests/test_textbook_pipeline_storage_name.py tests/test_textbook_autoyoutu_subprocess_env.py
```

Expected: PASS

**Step 5: Commit**

```bash
git add backend/app/ingest/textbook_pipeline.py backend/app/api/routers/textbooks.py backend/tests/test_textbook_graph_api.py backend/tests/test_textbook_pipeline_storage_name.py backend/tests/test_textbook_autoyoutu_subprocess_env.py
git rm backend/app/ingest/textbook_proposition_mapper.py backend/tests/test_textbook_proposition_mapping.py
git commit -m "refactor: rebuild communities after textbook ingest"
```

### Task 6: Remove proposition creation and proposition corpora from paper ingest and retrieval

**Files:**
- Modify: `backend/app/ingest/pipeline.py`
- Modify: `backend/app/rag/structured_retrieval.py`
- Modify: `backend/app/rag/service.py`
- Modify: `backend/app/rag/models.py`
- Modify: `backend/tests/test_rag_structured_retrieval.py`
- Modify: `backend/tests/test_rag_service.py`

**Step 1: Remove proposition mention writes from paper ingest**

Delete `upsert_proposition_mentions_for_claims()` calls and proposition clustering triggers.

**Step 2: Add a `communities` structured corpus**

Teach structured retrieval to load and search community rows instead of proposition rows.

**Step 3: Normalize community retrieval rows**

Add fields like:
- `community_id`
- `member_ids`
- `keyword_texts`
- `member_kinds`

**Step 4: Update Ask service retrieval orchestration**

Replace `retrieve_propositions()` usage with `retrieve_communities()` and then expand selected communities into member-backed evidence rows.

**Step 5: Run Ask and retrieval tests**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_rag_structured_retrieval.py tests/test_rag_service.py tests/test_rag_ask_v2_api.py
```

Expected: PASS

**Step 6: Commit**

```bash
git add backend/app/ingest/pipeline.py backend/app/rag/structured_retrieval.py backend/app/rag/service.py backend/app/rag/models.py backend/tests/test_rag_structured_retrieval.py backend/tests/test_rag_service.py backend/tests/test_rag_ask_v2_api.py
git commit -m "refactor: switch ask retrieval from propositions to communities"
```

### Task 7: Rewrite discovery from proposition-first to community-first

**Files:**
- Modify: `backend/app/discovery/models.py`
- Modify: `backend/app/discovery/gap_detector.py`
- Modify: `backend/app/discovery/context_builder.py`
- Modify: `backend/app/discovery/evidence_auditor.py`
- Modify: `backend/app/discovery/question_generator.py`
- Modify: `backend/app/discovery/service.py`
- Modify: `backend/tests/test_discovery_gap_detector.py`
- Modify: `backend/tests/test_discovery_context_builder.py`
- Modify: `backend/tests/test_discovery_pipeline.py`

**Step 1: Replace proposition IDs in discovery models**

Change `source_proposition_ids` to `source_community_ids`.

**Step 2: Rewrite gap mining rules**

Mine community-level signals such as:
- high member disagreement
- sparse evidence density
- textbook-heavy but paper-light coverage
- benchmark-poor communities

**Step 3: Rewrite context expansion**

Resolve papers, chapters, and evidence through community members rather than proposition mappings.

**Step 4: Rewrite evidence auditing**

Collect support and challenge material from community members and their evidence rows rather than proposition detail APIs.

**Step 5: Run discovery tests**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_discovery_gap_detector.py tests/test_discovery_context_builder.py tests/test_discovery_pipeline.py tests/test_discovery_api.py
```

Expected: PASS

**Step 6: Commit**

```bash
git add backend/app/discovery/models.py backend/app/discovery/gap_detector.py backend/app/discovery/context_builder.py backend/app/discovery/evidence_auditor.py backend/app/discovery/question_generator.py backend/app/discovery/service.py backend/tests/test_discovery_gap_detector.py backend/tests/test_discovery_context_builder.py backend/tests/test_discovery_pipeline.py backend/tests/test_discovery_api.py
git commit -m "refactor: make discovery community first"
```

### Task 8: Remove evolution, proposition groups, and their task/config/UI surface

**Files:**
- Delete: `backend/app/evolution/`
- Delete: `backend/app/api/routers/evolution.py`
- Delete: `backend/app/tasks/clustering_task.py`
- Modify: `backend/app/tasks/models.py`
- Modify: `backend/app/tasks/handlers.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/routers/tasks.py`
- Modify: `backend/app/api/routers/config_center.py`
- Delete: `frontend/src/panels/EvolutionPanel.tsx`
- Delete: `frontend/src/loaders/evolution.ts`
- Modify: `frontend/src/state/types.ts`
- Modify: `frontend/src/state/store.tsx`
- Modify: `frontend/src/components/StatusBar.tsx`
- Modify: `frontend/src/pages/TasksPage.tsx`
- Modify: `frontend/src/App.tsx`
- Delete or update: proposition/evolution frontend tests

**Step 1: Remove backend task and config wiring**

Delete:
- `rebuild_evolution`
- proposition clustering task
- proposition clustering config UI text

**Step 2: Remove backend evolution code and tests**

Delete evolution-specific modules and test files.

**Step 3: Remove frontend evolution entry points**

Delete the panel and loader, then remove module labels, state, and task buttons.

**Step 4: Remove or rewrite proposition-focused frontend tests**

Replace them with community-first Ask tests.

**Step 5: Run backend and frontend test subsets**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

Run:

```powershell
cd frontend
npm run test
```

Expected: PASS with no references to proposition or evolution modules.

**Step 6: Commit**

```bash
git add backend/app/tasks/models.py backend/app/tasks/handlers.py backend/app/main.py backend/app/api/routers/tasks.py backend/app/api/routers/config_center.py frontend/src/state/types.ts frontend/src/state/store.tsx frontend/src/components/StatusBar.tsx frontend/src/pages/TasksPage.tsx frontend/src/App.tsx
git rm -r backend/app/evolution backend/app/api/routers/evolution.py backend/app/tasks/clustering_task.py frontend/src/panels/EvolutionPanel.tsx frontend/src/loaders/evolution.ts
git commit -m "refactor: remove proposition and evolution modules"
```

### Task 9: Add Ask community graph rendering and remove proposition graph rendering

**Files:**
- Modify: `frontend/src/loaders/ask.ts`
- Modify: `frontend/src/components/RightPanel.tsx`
- Modify: `frontend/tests/askCommunityGraph.test.ts`
- Delete or replace: `frontend/tests/askPropositionGraph.test.ts`

**Step 1: Render community nodes in the Ask loader**

Build graph elements in this order:
- community
- member nodes
- evidence nodes

**Step 2: Remove proposition-specific node creation**

Delete graph building logic that assumes `proposition_id` rows.

**Step 3: Update the right panel**

Display community metadata, representative members, keywords, and evidence expansion results.

**Step 4: Run focused frontend tests**

Run:

```powershell
cd frontend
npm run test -- --run tests/askCommunityGraph.test.ts tests/askLoader.test.ts tests/askPanelModel.test.ts
```

Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/loaders/ask.ts frontend/src/components/RightPanel.tsx frontend/tests/askCommunityGraph.test.ts frontend/tests/askLoader.test.ts frontend/tests/askPanelModel.test.ts
git rm frontend/tests/askPropositionGraph.test.ts
git commit -m "feat: render community first ask graphs"
```

### Task 10: Add cleanup scripts and final verification

**Files:**
- Modify: `backend/app/graph/neo4j_client.py`
- Modify: `backend/app/ingest/rebuild.py`
- Modify: docs if commands change

**Step 1: Add graph cleanup helpers**

Add explicit deletion helpers for:
- `Proposition`
- `PropositionGroup`
- proposition-only edges
- stale proposition FAISS exports

**Step 2: Update rebuild/export paths**

Ensure rebuild/export no longer references proposition corpora.

**Step 3: Run full backend suite**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

**Step 4: Run full frontend suite**

Run:

```powershell
cd frontend
npm run lint
npm run test
npm run build
```

**Step 5: Run manual smoke verification**

Verify:
- textbook ingest still works
- community rebuild task succeeds
- Ask returns community-first evidence
- discovery returns community-based gaps
- no UI entry remains for evolution or proposition grouping

**Step 6: Commit**

```bash
git add backend/app/graph/neo4j_client.py backend/app/ingest/rebuild.py docs
git commit -m "chore: clean proposition artifacts and finalize community migration"
```
