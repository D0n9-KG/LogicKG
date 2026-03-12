# Discovery Removal Design

## Goal

Remove the `discovery` capability from LogicKG completely.

The final state should:

- remove all user-facing discovery entry points from the frontend
- remove all backend discovery runtime paths, APIs, tasks, and configuration
- delete stored discovery graph data and local discovery artifacts
- delete historical discovery task records and local config remnants
- ensure future ingest, rebuild, and startup flows never recreate discovery data
- preserve old frontend bookmarks by redirecting `/discovery` to `/ops`

The final product should have no active discovery workflow, no discovery management UI, and no discovery-specific persistence.

## Existing Context

`discovery` is currently spread across multiple parts of the codebase:

- backend runtime module in `backend/app/discovery/`
- API router in `backend/app/api/routers/discovery.py`
- task registration via `TaskType.discovery_batch` and `handle_discovery_batch`
- config-center defaults and assistant suggestions through `ops_config_store.py` and `config_center.py`
- frontend route and page in `frontend/src/pages/DiscoveryPage.tsx`
- frontend navigation, workbench shortcuts, overview statistics, and config-center panels
- Neo4j persistence for `KnowledgeGap`, `ResearchQuestion`, `ResearchQuestionCandidate`, `FeedbackRecord`, and `KnowledgeGapSeed`
- local artifacts such as `storage/discovery/prompt_policy_bandit.json`
- persisted task records in `backend/storage/tasks/*.json`

This means discovery removal is not only a UI deletion. It is a runtime, data, and storage cleanup effort.

## Approved Scope

### In scope

- delete the backend `app.discovery` package
- delete the `/discovery` backend API surface
- delete `discovery_batch` task registration, handler, and task type
- delete discovery-specific config defaults, config-center fields, and settings
- delete discovery persistence helpers and discovery seed generation from graph/ingest flows
- delete stored discovery graph data from Neo4j
- delete local discovery artifacts, including prompt policy files and task records
- delete the frontend discovery page, navigation, overview summary, and config-center panel
- redirect the frontend `/discovery` route to `/ops`
- remove or rewrite tests that still expect discovery behavior
- update active product-facing docs and labels so discovery is not presented as a current capability

### Out of scope

- replacing discovery with a new feature
- keeping a read-only discovery history UI
- adding a long-lived compatibility backend route for `/discovery`
- automatic cleanup on startup or any hidden cleanup side effect
- rewriting archived historical design and plan documents that mention discovery as past work
- introducing a new general-purpose migration framework for one-off cleanup work

## Key Decisions

### 1. Remove discovery in one hard cut

Discovery should be removed as a whole feature, not soft-deprecated.

We will not keep:

- hidden backend routes
- read-only discovery data access
- dormant config sections
- dead task types
- dormant prompt-policy files

This keeps the codebase in a true final state instead of leaving partial compatibility layers behind.

### 2. Cleanup is explicit and idempotent

Stored discovery data should be removed through an explicit cleanup unit that is safe to run more than once.

The cleanup must:

- succeed when some or all discovery data is already gone
- avoid startup-time side effects
- avoid depending on the frontend
- produce structured output so cleanup can be verified

### 3. Historical traces are deleted, not merely hidden

The approved scope includes local operational residue, not only graph nodes.

That means cleanup must also remove:

- `modules.discovery` from stored config-center profiles
- `discovery_batch` task JSON records under `backend/storage/tasks/`
- local discovery prompt-policy files or directories

### 4. `/discovery` should redirect, not disappear abruptly

The frontend route `/discovery` should redirect to `/ops`.

This provides a stable landing place for old bookmarks and avoids adding a temporary explanatory page. The backend does not need a compatibility route; if a caller still hits the removed API, `404` is acceptable.

### 5. `KnowledgeGapSeed` is discovery-owned data

`KnowledgeGapSeed` currently exists to feed downstream discovery generation. Once discovery is removed, it no longer serves a live product workflow.

It should therefore be treated as discovery-owned persistence and removed together with:

- `KnowledgeGap`
- `ResearchQuestion`
- `ResearchQuestionCandidate`
- `FeedbackRecord`

## Design

## Backend Runtime Removal

### Delete discovery application code

Remove the runtime discovery package and its direct integrations:

- `backend/app/discovery/`
- `backend/app/api/routers/discovery.py`
- `backend/app/main.py` imports and router registration
- `backend/app/tasks/handlers.py` discovery handler and imports
- `backend/app/tasks/models.py` `TaskType.discovery_batch`

After this change:

- the backend no longer exposes `/discovery/*`
- task registration no longer includes discovery batch work
- no runtime import path depends on discovery code

### Remove discovery-specific configuration

Delete discovery configuration support from:

- `backend/app/ops_config_store.py`
- `backend/app/api/routers/config_center.py`
- `backend/app/settings.py`

Required effects:

- `default_profile()` no longer creates `modules.discovery`
- profile normalization drops any existing `modules.discovery` payload when loading and saving
- config-center assistant suggestions never emit `discovery.*` anchors
- `/config-center/effective/discovery` no longer exists
- `Settings.discovery_prompt_policy_path` is removed

### Remove graph-side discovery persistence helpers

Delete discovery-specific graph helpers from `backend/app/graph/neo4j_client.py`, including:

- discovery schema constraints and indexes
- discovery persistence helpers such as `upsert_discovery_graph`
- discovery query helpers that only serve the removed feature
- `KnowledgeGapSeed` creation during claim ingest

After this change, ingest and rebuild flows must stop producing any discovery-owned graph data.

## Discovery Cleanup Unit

### Placement

Implement cleanup logic as a backend maintenance unit, not as a product feature.

Recommended placement:

- cleanup orchestration in `backend/app/ingest/rebuild.py`, next to other graph/storage cleanup routines
- low-level graph cleanup helpers in `backend/app/graph/neo4j_client.py`
- local storage cleanup helpers in the task/config storage modules or adjacent utility functions

This follows existing repository structure without inventing a new migration framework.

### Responsibilities

The cleanup unit should remove discovery residues from three places:

#### 1. Neo4j graph data

Delete discovery-owned nodes and their relationships:

- `KnowledgeGap`
- `ResearchQuestion`
- `ResearchQuestionCandidate`
- `FeedbackRecord`
- `KnowledgeGapSeed`

Also drop discovery-owned schema objects:

- uniqueness constraints
- indexes tied to the deleted labels

Graph cleanup must report counts for deleted nodes and dropped schema objects.

#### 2. Local filesystem artifacts

Delete discovery-owned local files if present:

- `storage/discovery/`
- prompt-policy JSON files
- any other discovery-only local artifact directory created by the removed module

Filesystem cleanup must tolerate missing paths.

#### 3. Stored config and task history

Cleanup must also purge local operational residue:

- load and resave config-center profile data without `modules.discovery`
- delete task JSON files whose stored `type` is `discovery_batch`

Task-history cleanup should inspect file contents, not filenames, so the purge remains correct even if task IDs are arbitrary.

### Invocation model

Cleanup should be run explicitly through an operator/developer maintenance command or script. It must not run automatically on app startup.

The cleanup path should:

- be callable without the frontend
- return structured counts for graph, schema, config, task, and filesystem cleanup
- remain safe if re-run after a partial cleanup

### No automatic rebuild after cleanup

Discovery nodes do not define the active graph structures used by Ask, communities, or FAISS.

For that reason, discovery cleanup should not automatically trigger:

- global community rebuild
- global FAISS rebuild

If implementation uncovers a real dependency that requires rebuild, that should be justified explicitly during planning. The default design is to avoid unnecessary rebuild work.

## Frontend Design

### Remove discovery surfaces

Delete discovery-specific frontend files and integrations:

- `frontend/src/pages/DiscoveryPage.tsx`
- `frontend/src/pages/discovery.css`
- discovery route entry in `frontend/src/App.tsx`
- discovery navigation item in `frontend/src/components/TopBar.tsx`
- discovery shortcut button in the workbench shell
- discovery summary card and CTA from `frontend/src/panels/OverviewPanel.tsx`
- discovery loader state from `frontend/src/loaders/panelData.ts`
- discovery config tab and form state from `frontend/src/pages/ConfigCenterPage.tsx`

### Redirect old route

The frontend route `/discovery` should redirect to `/ops`.

This redirect belongs in the router configuration and should replace the old page route. No new explanatory page is needed.

### Overview simplification

The overview loader and panel should stop requesting discovery candidates.

`OverviewStatsSnapshot` should only describe data that still exists in the product. Discovery-specific counts, summaries, and quality-score text should be removed entirely.

### Config-center simplification

Config Center should no longer model discovery as a configurable module.

That means removing:

- `DiscoveryConfig` types
- default state initialization for discovery
- discovery tab rendering
- discovery anchor routing and flash behavior
- discovery write-back logic

After the change, Config Center should only expose modules that remain live in the product.

## Testing Design

### Delete discovery-specific tests

Remove backend and frontend tests whose only purpose is to validate discovery behavior, including discovery API, pipeline, prompt-policy, and graph-model tests.

Examples include:

- backend tests named `test_discovery_*`
- frontend tests that mock `/discovery/candidates`

### Rewrite affected non-discovery tests

Update tests that currently mention discovery as part of broader product behavior.

Required updates include:

- `backend/tests/test_app_main.py`
  - stop expecting `TaskType.discovery_batch`
  - stop expecting discovery routes to be registered
- `backend/tests/test_config_center_api.py`
  - stop expecting `modules.discovery`
  - stop expecting `discovery.*` assistant anchors
- `frontend/tests/panelDataLoader.test.ts`
  - stop mocking or asserting `/discovery/candidates`
  - assert overview stats using only still-live data
- `frontend/tests/workspaceData.test.ts`
  - remove discovery-backed cache expectations

### Add focused cleanup coverage

Add targeted tests for the new cleanup unit.

The cleanup tests should cover:

- deleting discovery nodes and schema objects when present
- succeeding when graph data is already absent
- removing `modules.discovery` from stored config
- deleting `discovery_batch` task files from task storage
- deleting `storage/discovery` artifacts when present

## Documentation Boundary

Update active product-facing copy and docs so discovery is not described as a current feature.

Do not rewrite archived historical records such as old plan/spec files that mention discovery as part of past migration work. Those documents can remain as historical artifacts.

## Rollout Order

1. Implement the explicit cleanup unit and its tests
2. Run cleanup against the target local data/store so discovery residues are removed
3. Remove backend runtime code, config, graph helpers, and seed generation
4. Remove frontend routes, UI, overview references, and config-center surfaces
5. Rewrite or delete affected tests
6. Run verification commands and data checks

This order keeps cleanup available while residues still exist, then moves the codebase to its final no-discovery state.

## Validation Targets

The removal is successful when all of the following are true:

- the backend exposes no `/discovery` routes
- the backend no longer defines `TaskType.discovery_batch`
- config-center responses contain no `modules.discovery` data or `discovery.*` anchors
- ingest and rebuild code no longer create `KnowledgeGapSeed` or other discovery-owned nodes
- the frontend has no discovery page, navigation item, overview widget, or config panel
- `/discovery` redirects to `/ops`
- Neo4j contains no `KnowledgeGap`, `ResearchQuestion`, `ResearchQuestionCandidate`, `FeedbackRecord`, or `KnowledgeGapSeed` nodes
- discovery-owned constraints and indexes are gone
- `backend/storage/tasks/` contains no persisted `discovery_batch` records
- `storage/discovery/` and discovery prompt-policy artifacts are gone
- backend and frontend test suites pass after the discovery references are removed
