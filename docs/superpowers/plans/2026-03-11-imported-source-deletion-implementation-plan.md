# Imported Source Deletion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add frontend deletion flows for imported papers and textbooks, including side-panel single delete, `/ingest` batch delete, and one automatic post-delete rebuild per successful batch.

**Architecture:** Keep deletion UX split across side panels and `/ingest`, but converge execution behind task-based backend delete handlers. Introduce a dedicated paper management API for `/ingest`, reusable delete services for paper and textbook assets, and a small frontend management layer that keeps panel refresh, cache invalidation, and task polling consistent.

**Tech Stack:** FastAPI, React 19 + Vite + TypeScript, Neo4j, existing task queue in `backend/app/tasks`, Vitest, pytest

---

## File Structure

### Backend

- Create: `backend/app/delete_assets.py`
  Single responsibility: reusable deletion services for paper/textbook assets, including graph deletion and derived-file cleanup.
- Modify: `backend/app/api/routers/papers.py`
  Add paper management list endpoint for `/ingest`.
- Modify: `backend/app/api/routers/tasks.py`
  Add task submission endpoints for paper/textbook delete batches.
- Modify: `backend/app/api/routers/paper_edits.py`
  Repoint legacy single-paper delete router logic to shared service or reduce it to a thin wrapper.
- Modify: `backend/app/api/routers/textbooks.py`
  Repoint textbook delete router logic to shared service or reduce it to a thin wrapper.
- Modify: `backend/app/tasks/models.py`
  Register new task types for batch deletion.
- Modify: `backend/app/tasks/handlers.py`
  Add batch delete handlers and one shared rebuild tail.
- Modify: `backend/app/main.py`
  Register the new task handlers.
- Modify: `backend/app/graph/neo4j_client.py`
  Add a management-oriented paper listing query and keep textbook deletion semantics explicit.
- Create: `backend/tests/test_paper_management_api.py`
  Validate `/papers/manage` contract and grouping support data.
- Create: `backend/tests/test_delete_assets_service.py`
  Validate reusable paper/textbook delete service behavior, including textbook artifact cleanup rules.
- Create: `backend/tests/test_delete_batch_tasks.py`
  Validate batch delete task results, partial success rules, and rebuild semantics.
- Modify: `backend/tests/test_paper_delete_hard_delete.py`
  Keep existing single-delete behavior covered after refactor.

### Frontend

- Modify: `frontend/package.json`
  Add DOM-oriented Vitest dev dependencies needed by the new panel and `/ingest` interaction tests.
- Modify: `frontend/vite.config.ts`
  Register the Vitest `jsdom` environment and shared setup file for DOM tests.
- Create: `frontend/src/loaders/sourceManagement.ts`
  Management-specific loaders and task submit helpers for `/ingest`.
- Create: `frontend/tests/setup.ts`
  Shared Vitest DOM setup, including cleanup and `jest-dom` matchers.
- Create: `frontend/src/pages/ImportedSourceManagement.tsx`
  Dedicated UI block for paper/textbook management so `IngestPage.tsx` does not absorb all new behavior.
- Modify: `frontend/src/pages/IngestPage.tsx`
  Mount the new management section and reuse existing task UI patterns.
- Modify: `frontend/src/panels/PapersPanel.tsx`
  Switch single delete to task submission + polling + refresh flow.
- Modify: `frontend/src/panels/TextbooksPanel.tsx`
  Add single textbook delete affordance and matching task behavior.
- Modify: `frontend/src/loaders/panelData.ts`
  Add management cache invalidation helpers or shared textbook cache usage needed by the new UI.
- Create: `frontend/tests/sourceManagementLoader.test.ts`
  Validate management loaders and cache invalidation behavior.
- Create: `frontend/tests/importedSourceManagement.test.tsx`
  Validate grouped paper rendering, metadata-only non-deletable rows, and batch action UI.
- Create: `frontend/tests/ingestPage.test.tsx`
  Guard the existing upload/scan/task workflow against regressions after mounting the new management section.
- Create: `frontend/tests/papersPanelDelete.test.tsx`
  Validate paper single-delete task submission, selected-state reset, and post-delete graph recovery.
- Create: `frontend/tests/textbooksPanel.test.tsx`
  Validate textbook single-delete affordance and task-driven refresh behavior.
- Modify: `frontend/tests/panelDataLoader.test.ts`
  Cover any changed cache invalidation semantics.

### Docs

- Modify: `docs/superpowers/specs/2026-03-11-imported-source-deletion-design.md`
  Only if implementation uncovers a mismatch. Do not expand scope silently.

## Chunk 1: Backend Delete Infrastructure

### Task 1: Add failing backend tests for the new contracts

**Files:**
- Create: `backend/tests/test_paper_management_api.py`
- Create: `backend/tests/test_delete_batch_tasks.py`
- Modify: `backend/tests/test_paper_delete_hard_delete.py`

- [ ] **Step 1: Write the failing `/papers/manage` API test**

```python
def test_papers_manage_includes_ingested_and_metadata_only(client):
    response = client.get("/papers/manage?limit=20")
    payload = response.json()
    assert payload["papers"][0]["display_title"] == "Readable Title"
    assert {row["ingested"] for row in payload["papers"]} == {True, False}
    assert any(row["deletable"] is False for row in payload["papers"])
```

- [ ] **Step 2: Run the new API test to verify it fails**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_paper_management_api.py`
Expected: FAIL because `/papers/manage` does not exist yet.

- [ ] **Step 3: Write the failing batch-delete task tests**

```python
def test_delete_papers_batch_reports_partial_success_and_rebuild_once():
    result = handle_delete_papers_batch(...)
    assert result["deleted_count"] == 1
    assert result["failed_count"] == 1
    assert result["rebuild"]["status"] == "succeeded"

def test_delete_papers_batch_skips_metadata_only_and_duplicates():
    result = handle_delete_papers_batch(...)
    assert result["skipped_count"] == 2
```

- [ ] **Step 4: Run the batch-delete tests to verify they fail**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_delete_batch_tasks.py`
Expected: FAIL because new task types and handlers are not implemented.

- [ ] **Step 5: Update the legacy single-paper delete regression test to reflect shared-service wiring**

```python
def test_delete_defaults_to_hard_delete():
    out = delete_ingested_paper("doi:10.1234/test")
    assert out["hard_delete"] is True
```

- [ ] **Step 6: Run the legacy delete test to capture current behavior before refactor**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_paper_delete_hard_delete.py`
Expected: PASS before refactor, then keep it passing through the refactor.

- [ ] **Step 7: Commit the failing-test scaffold**

```bash
git add backend/tests/test_paper_management_api.py backend/tests/test_delete_batch_tasks.py backend/tests/test_paper_delete_hard_delete.py
git commit -m "test: add deletion management backend coverage"
```

### Task 2: Implement reusable delete services and management query

**Files:**
- Create: `backend/app/delete_assets.py`
- Modify: `backend/app/graph/neo4j_client.py`
- Modify: `backend/app/api/routers/papers.py`
- Modify: `backend/app/api/routers/paper_edits.py`
- Modify: `backend/app/api/routers/textbooks.py`
- Create: `backend/tests/test_delete_assets_service.py`

- [ ] **Step 1: Write failing service tests for textbook artifact cleanup and metadata-only protection**

```python
def test_delete_textbook_asset_removes_storage_textbooks_artifacts_only():
    result = delete_textbook_asset("tb:test")
    assert result["removed"]["artifact_dir"] is True
    assert result["removed"]["source_dir"] is False

def test_delete_paper_asset_skips_metadata_only_paper():
    result = delete_paper_asset("doi:10.1234/stub")
    assert result["skipped"] is True
    assert result["reason"] == "metadata_only"
```

- [ ] **Step 2: Run the service tests to verify they fail**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_delete_assets_service.py`
Expected: FAIL because the shared delete service and metadata-only guard do not exist yet.

- [ ] **Step 3: Create the shared delete service module**

```python
def delete_paper_asset(paper_id: str, hard_delete: bool = True) -> dict[str, Any]: ...
def delete_textbook_asset(textbook_id: str) -> dict[str, Any]: ...
```

Include:

- existence lookup
- graph delete orchestration
- safe derived-file cleanup
- structured return payload for task aggregation

- [ ] **Step 4: Add a management-oriented paper listing query to `Neo4jClient`**

```python
def list_papers_for_management(self, limit: int = 200, query: str | None = None) -> list[dict]:
    return [
        {
            "paper_id": "...",
            "display_title": "...",
            "ingested": True,
            "deletable": True,
        }
    ]
```

It must return both ingested and metadata-only paper nodes.

- [ ] **Step 5: Add `/papers/manage` as a thin router over the new query**

Run path: `backend/app/api/routers/papers.py`
Expected contract: `GET /papers/manage?limit=...&q=...`

- [ ] **Step 6: Rewire paper and textbook single-delete routers to use the shared service**

Keep router responsibilities thin:

- request parsing
- HTTP error mapping
- service call

For the legacy paper delete route, explicitly close the metadata-only loophole:

- shared service returns a skipped result when `ingested = false`
- route preserves that outcome instead of hard-deleting the stub node

- [ ] **Step 7: Run focused backend tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_delete_assets_service.py tests/test_paper_management_api.py tests/test_paper_delete_hard_delete.py`
Expected: PASS

- [ ] **Step 8: Commit the shared delete service and management query**

```bash
git add backend/app/delete_assets.py backend/app/graph/neo4j_client.py backend/app/api/routers/papers.py backend/app/api/routers/paper_edits.py backend/app/api/routers/textbooks.py backend/tests/test_delete_assets_service.py backend/tests/test_paper_management_api.py backend/tests/test_paper_delete_hard_delete.py
git commit -m "feat: add shared asset deletion services"
```

### Task 3: Implement delete task types, handlers, and rebuild tail

**Files:**
- Modify: `backend/app/delete_assets.py`
- Modify: `backend/app/tasks/models.py`
- Modify: `backend/app/tasks/handlers.py`
- Modify: `backend/app/tasks/manager.py`
- Modify: `backend/app/api/routers/tasks.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_delete_batch_tasks.py`

- [ ] **Step 1: Extract a pure batch-delete helper seam from the task handlers**

Keep the public task handlers thin and move the batch logic into testable helpers that accept normalized payload data directly.

Suggested shape:

```python
def run_delete_papers_batch(payload: dict[str, Any], update, log) -> dict[str, Any]: ...
def run_delete_textbooks_batch(payload: dict[str, Any], update, log) -> dict[str, Any]: ...
```

- [ ] **Step 2: Update the batch-delete tests to target the pure helper seam**

```python
def test_delete_papers_batch_reports_partial_success_and_rebuild_once():
    result = run_delete_papers_batch(payload, update, log)
    assert result["deleted_count"] == 1
    assert result["failed_count"] == 1
```

- [ ] **Step 3: Run the batch-delete tests to verify they still fail**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_delete_batch_tasks.py`
Expected: FAIL because the helper seam and task types are not implemented yet.

- [ ] **Step 4: Add new task types and handlers for paper/textbook batch deletion**

```python
class TaskType(str, Enum):
    delete_papers_batch = "delete_papers_batch"
    delete_textbooks_batch = "delete_textbooks_batch"
```

```python
def handle_delete_papers_batch(task_id, update, log): ...
def handle_delete_textbooks_batch(task_id, update, log): ...
```

Make the failure contract explicit here:

- handlers must accumulate per-item results in memory
- if rebuild fails after successful deletions, raise or return through one structured path that preserves the accumulated delete summary
- `TaskManager` must persist that partial `result` even when final task status becomes `failed`

- [ ] **Step 5: Add task submission endpoints**

Endpoints:

- `POST /tasks/delete/papers`
- `POST /tasks/delete/textbooks`

Each should submit a task and return `task_id`.

- [ ] **Step 6: Implement one shared rebuild tail inside the delete helpers**

```python
if deleted_count > 0 and trigger_rebuild:
    communities = app.community.service.rebuild_global_communities(...)
    faiss = app.ingest.rebuild.rebuild_global_faiss(...)
```

Call the already-existing community rebuild path from `backend/app/tasks/handlers.py`; do not switch this delete tail to `rebuild_fusion_graph(...)`.

If rebuild fails after a successful delete, the task record should become `failed` while still carrying delete results.

- [ ] **Step 7: Teach `TaskManager` to preserve partial results on failure**

Use one explicit mechanism and keep it consistent:

- a structured exception carrying partial `result`
- or a failure envelope that the manager persists before marking the task failed

Do not leave this behavior implicit.

- [ ] **Step 8: Run focused backend regression tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_delete_assets_service.py tests/test_delete_batch_tasks.py tests/test_paper_management_api.py tests/test_paper_delete_hard_delete.py`
Expected: PASS

- [ ] **Step 9: Run a broader backend confidence sweep**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_textbook_graph_helpers.py tests/test_textbook_pipeline_storage_name.py tests/test_papers_api.py`
Expected: PASS to confirm router-level regressions were not introduced.

- [ ] **Step 10: Commit the backend task layer**

```bash
git add backend/app/delete_assets.py backend/app/tasks/models.py backend/app/tasks/handlers.py backend/app/tasks/manager.py backend/app/api/routers/tasks.py backend/app/main.py backend/tests/test_delete_assets_service.py backend/tests/test_delete_batch_tasks.py
git commit -m "feat: add task-based asset deletion"
```

## Chunk 2: Frontend Single-Delete Flows

### Task 4: Add failing frontend tests for side-panel delete behavior

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/tests/setup.ts`
- Create: `frontend/tests/papersPanelDelete.test.tsx`
- Create: `frontend/tests/textbooksPanel.test.tsx`
- Modify: `frontend/tests/panelDataLoader.test.ts`

- [ ] **Step 1: Add DOM test infrastructure for interaction-heavy panel tests**

Install the missing dev dependencies and register Vitest DOM support before writing interaction tests that use `render`, `screen`, and `userEvent`.

```ts
// frontend/vite.config.ts
test: {
  environment: 'jsdom',
  globals: true,
  setupFiles: './tests/setup.ts',
}
```

```ts
// frontend/tests/setup.ts
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'

afterEach(() => {
  cleanup()
})
```

Dev dependencies to add in `frontend/package.json`:

- `@testing-library/jest-dom`
- `@testing-library/react`
- `@testing-library/user-event`
- `jsdom`

For the panel tests, also make the app-level seams explicit instead of relying on real providers:

```tsx
beforeEach(() => {
  vi.mocked(useI18n).mockReturnValue({ locale: 'en-US', t: (_zh, en) => en })
  vi.mocked(loadPaperCatalog).mockResolvedValue([{ paper_id: 'doi:10.1234/test', paper_source: 'attention', title: 'Attention Is All You Need', ingested: true, collections: [] }])
  vi.mocked(loadPaperCollections).mockResolvedValue([])
  vi.mocked(loadTextbookCatalog).mockResolvedValue([{ textbook_id: 'tb-1', title: 'Deep Learning', chapter_count: 3, entity_count: 42 }])
  vi.mocked(apiPost).mockResolvedValue({ task_id: 'task-1' })
})

function renderPanelWithState(ui: React.ReactElement, stateOverrides: Partial<GlobalState> = {}) {
  const dispatch = vi.fn()
  vi.mocked(useGlobalState).mockReturnValue({
    state: { ...INITIAL_STATE, ...stateOverrides },
    dispatch,
    switchModule: vi.fn(),
  })
  return { dispatch, ...render(ui) }
}
```

- [ ] **Step 2: Create a minimal DOM-based `PapersPanel` smoke test**

```tsx
test('renders the papers panel inside jsdom without environment errors', () => {
  renderPanelWithState(<PapersPanel />)
  expect(screen.getByPlaceholderText(/search papers/i)).toBeInTheDocument()
})
```

- [ ] **Step 3: Run the smoke test to verify the DOM harness works**

Run: `cd frontend; npm run test -- papersPanelDelete.test.tsx`
Expected: PASS, proving the new `jsdom` + Testing Library harness is wired correctly before the behavior-specific red tests are added.

- [ ] **Step 4: Write the failing `PapersPanel` task-delete regression tests**

Use the same explicit polling seam planned for `/ingest` tests:

```tsx
function mockLoadDeleteTaskSequence(...responses: Array<Record<string, unknown>>) {
  const queue = [...responses]
  const last = responses[responses.length - 1]
  vi.mocked(loadDeleteTask).mockImplementation(async () => queue.shift() ?? last)
}
```

```tsx
test('submits paper delete task and refreshes the paper catalog', async () => {
  renderPanelWithState(<PapersPanel />)
  await user.click(screen.getByRole('button', { name: /delete/i }))
  expect(apiPost).toHaveBeenCalledWith('/tasks/delete/papers', { paper_ids: ['doi:10.1234/test'], trigger_rebuild: true })
})

test('shows delete confirmation copy for graph data, derived files, and the automatic rebuild', async () => {
  renderPanelWithState(<PapersPanel />)
  await user.click(screen.getByRole('button', { name: /delete/i }))
  expect(screen.getByText(/remove neo4j graph data, derived files, and trigger one rebuild/i)).toBeInTheDocument()
})

test('clears the selected paper and uses the existing unselected-paper recovery path after deleting the active paper', async () => {
  const { dispatch } = renderPanelWithState(<PapersPanel />, { activeModule: 'papers', papers: { selectedPaperId: 'doi:10.1234/test', searchQuery: '' } })
  await user.click(screen.getByRole('button', { name: /delete/i }))
  await user.click(screen.getByRole('button', { name: /confirm delete/i }))
  await waitFor(() => expect(dispatch).toHaveBeenCalledWith({ type: 'PAPERS_SELECT', paperId: null }))
  expect(loadOverviewGraph).toHaveBeenCalledWith(200, 600, { includeTextbooks: false })
})

test('surfaces rebuild failure when the paper delete succeeded but the post-delete rebuild failed', async () => {
  renderPanelWithState(<PapersPanel />)
  mockLoadDeleteTaskSequence(
    { status: 'queued', progress: 0 },
    { status: 'failed', error: 'global rebuild failed', result: { deleted_count: 1, failed_count: 0, skipped_count: 0 } },
  )
  await user.click(screen.getByRole('button', { name: /delete/i }))
  await user.click(screen.getByRole('button', { name: /confirm delete/i }))
  await waitFor(() => expect(screen.getByText(/paper deleted, but rebuild failed/i)).toBeInTheDocument())
})

test('invalidates paper and overview caches after a successful paper delete task', async () => {
  renderPanelWithState(<PapersPanel />)
  mockLoadDeleteTaskSequence(
    { status: 'queued', progress: 0 },
    { status: 'succeeded', result: { deleted_count: 1, failed_count: 0, skipped_count: 0 } },
  )
  await user.click(screen.getByRole('button', { name: /delete/i }))
  await user.click(screen.getByRole('button', { name: /confirm delete/i }))
  await waitFor(() => expect(invalidatePaperDataCache).toHaveBeenCalled())
  expect(invalidateOverviewStatsCache).toHaveBeenCalled()
  expect(invalidateOverviewGraphCache).toHaveBeenCalled()
})
```

- [ ] **Step 5: Write the failing `TextbooksPanel` delete test**

```tsx
test('submits textbook delete task and refreshes catalog', async () => {
  renderPanelWithState(<TextbooksPanel />)
  await user.click(screen.getByRole('button', { name: /delete/i }))
  expect(apiPost).toHaveBeenCalledWith('/tasks/delete/textbooks', { textbook_ids: ['tb-1'], trigger_rebuild: true })
})

test('resets textbook and chapter selection after deleting the active textbook', async () => {
  const { dispatch } = renderPanelWithState(<TextbooksPanel />, { activeModule: 'textbooks', textbooks: { selectedTextbookId: 'tb-1', selectedChapterId: 'ch-1' } })
  await user.click(screen.getByRole('button', { name: /delete/i }))
  await user.click(screen.getByRole('button', { name: /confirm delete/i }))
  await waitFor(() => expect(dispatch).toHaveBeenCalledWith({ type: 'TEXTBOOKS_SELECT', textbookId: null, chapterId: null }))
})

test('shows textbook delete confirmation copy and rebuild-failure messaging', async () => {
  renderPanelWithState(<TextbooksPanel />)
  await user.click(screen.getByRole('button', { name: /delete/i }))
  expect(screen.getByText(/remove textbook graph data, derived files, and trigger one rebuild/i)).toBeInTheDocument()
  mockLoadDeleteTaskSequence(
    { status: 'queued', progress: 0 },
    { status: 'failed', error: 'global rebuild failed', result: { deleted_count: 1, failed_count: 0, skipped_count: 0 } },
  )
  await user.click(screen.getByRole('button', { name: /confirm delete/i }))
  await waitFor(() => expect(screen.getByText(/textbook deleted, but rebuild failed/i)).toBeInTheDocument())
})

test('invalidates textbook and overview caches after a successful textbook delete task', async () => {
  renderPanelWithState(<TextbooksPanel />)
  mockLoadDeleteTaskSequence(
    { status: 'queued', progress: 0 },
    { status: 'succeeded', result: { deleted_count: 1, failed_count: 0, skipped_count: 0 } },
  )
  await user.click(screen.getByRole('button', { name: /delete/i }))
  await user.click(screen.getByRole('button', { name: /confirm delete/i }))
  await waitFor(() => expect(invalidateTextbookCatalogCache).toHaveBeenCalled())
  expect(invalidateOverviewStatsCache).toHaveBeenCalled()
  expect(invalidateOverviewGraphCache).toHaveBeenCalled()
})
```

- [ ] **Step 6: Extend loader cache tests so invalidation proves a second fetch occurs**

```ts
test('invalidates paper catalog cache and refetches on the next load', async () => {
  await loadPaperCatalog('all')
  expect(apiGet).toHaveBeenCalledTimes(1)

  invalidatePaperDataCache()
  await loadPaperCatalog('all')

  expect(apiGet).toHaveBeenCalledTimes(2)
})

test('invalidates textbook catalog cache and refetches on the next load', async () => {
  await loadTextbookCatalog(100)
  expect(apiGet).toHaveBeenCalledTimes(1)

  invalidateTextbookCatalogCache()
  await loadTextbookCatalog(100)

  expect(apiGet).toHaveBeenCalledTimes(2)
})
```

- [ ] **Step 7: Run the new panel and loader tests to verify they fail**

Run: `cd frontend; npm run test -- papersPanelDelete.test.tsx textbooksPanel.test.tsx panelDataLoader.test.ts`
Expected: FAIL because the task-based delete buttons, confirmation copy, selected-state reset, rebuild-failure messaging, and delete-driven refresh flow do not exist yet.

- [ ] **Step 8: Commit the failing frontend test scaffold**

```bash
git add frontend/package.json frontend/vite.config.ts frontend/tests/setup.ts frontend/tests/papersPanelDelete.test.tsx frontend/tests/textbooksPanel.test.tsx frontend/tests/panelDataLoader.test.ts
git commit -m "test: add frontend deletion panel coverage"
```

### Task 5: Add shared delete-task client helpers and panel wiring

**Files:**
- Create: `frontend/src/loaders/sourceManagement.ts`
- Modify: `frontend/src/panels/PapersPanel.tsx`
- Modify: `frontend/src/panels/TextbooksPanel.tsx`
- Modify: `frontend/src/loaders/panelData.ts`

- [ ] **Step 1: Create shared delete-task helpers**

```ts
export type DeleteTaskSummary = {
  deleted_count: number
  failed_count: number
  skipped_count: number
  rebuild?: { status?: string; error?: string | null }
  items?: Array<{ id: string; status: 'deleted' | 'failed' | 'skipped'; reason?: string }>
}

export async function submitPaperDeleteTask(paperIds: string[]): Promise<{ task_id: string }> {
  return apiPost('/tasks/delete/papers', { paper_ids: paperIds, trigger_rebuild: true })
}

export async function submitTextbookDeleteTask(textbookIds: string[]): Promise<{ task_id: string }> {
  return apiPost('/tasks/delete/textbooks', { textbook_ids: textbookIds, trigger_rebuild: true })
}

export async function loadDeleteTask(taskId: string): Promise<{
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
  progress?: number
  error?: string | null
  result?: DeleteTaskSummary
}> {
  return apiGet(`/tasks/${encodeURIComponent(taskId)}`)
}
```

Keep this file focused on management/delete task APIs, not generic task UI.

- [ ] **Step 2: Refactor `PapersPanel` single delete to submit a delete task**

Maintain:

- existing confirmation modal
- list refresh
- cache invalidation

Change:

- direct `apiDelete('/papers/...')` call becomes task submission plus polling
- update the confirmation modal copy to mention graph data removal, derived-file cleanup, and the automatic post-delete rebuild
- if the deleted paper is the active selection, clear `papers.selectedPaperId`, cancel any stale `selectReqRef`, and route through the existing unselected-paper recovery path; when the current graph cannot supply that neutral state, fall back to `loadOverviewGraph(200, 600, { includeTextbooks: false })`
- if the delete task returns `failed` with a non-zero `deleted_count`, surface a message that the paper was deleted but the post-delete rebuild failed
- keep the post-delete refresh observable in tests by awaiting the catalog reload path instead of only invalidating caches

- [ ] **Step 3: Add single-delete UI and task flow to `TextbooksPanel`**

Keep the panel lightweight:

- delete button per textbook row
- confirmation modal
- task submission
- refresh and selection clearing after completion
- update the confirmation modal copy to mention graph data removal, derived-file cleanup, and the automatic post-delete rebuild
- if the deleted textbook or selected chapter belonged to the deleted textbook, dispatch `TEXTBOOKS_SELECT` back to `{ textbookId: null, chapterId: null }`
- if the delete task returns `failed` with a non-zero `deleted_count`, surface a message that the textbook was deleted but the post-delete rebuild failed

- [ ] **Step 4: Make cache invalidation explicit and reusable**

Use or extend:

- `invalidatePaperDataCache()`
- `invalidateTextbookCatalogCache()`
- `invalidateOverviewGraphCache()`
- `invalidateOverviewStatsCache()`

Reuse `frontend/src/loaders/overview.ts` as-is for overview-cache invalidation; this chunk should call the existing helper, not redesign the overview loader.

- [ ] **Step 5: Run focused frontend tests**

Run: `cd frontend; npm run test -- papersPanelDelete.test.tsx textbooksPanel.test.tsx panelDataLoader.test.ts`
Expected: PASS

- [ ] **Step 6: Run frontend static verification**

Run: `cd frontend; npm run lint`
Expected: PASS

- [ ] **Step 7: Run frontend type/build verification**

Run: `cd frontend; npm run build`
Expected: PASS

- [ ] **Step 8: Commit the single-delete frontend flow**

```bash
git add frontend/src/loaders/sourceManagement.ts frontend/src/panels/PapersPanel.tsx frontend/src/panels/TextbooksPanel.tsx frontend/src/loaders/panelData.ts frontend/tests/papersPanelDelete.test.tsx frontend/tests/textbooksPanel.test.tsx frontend/tests/panelDataLoader.test.ts
git commit -m "feat: route panel deletion through tasks"
```

## Chunk 3: `/ingest` Management UI

### Task 6: Add failing tests for grouped management and batch delete UI

**Files:**
- Create: `frontend/tests/sourceManagementLoader.test.ts`
- Create: `frontend/tests/importedSourceManagement.test.tsx`
- Create: `frontend/tests/ingestPage.test.tsx`

Reuse the DOM test harness added in Task 4 (`frontend/vite.config.ts` + `frontend/tests/setup.ts`). Do not create a second frontend test setup path here.

- [ ] **Step 1: Write failing loader tests for `/papers/manage`**

```ts
test('loads paper management rows with display titles and deletable flags', async () => {
  const rows = await loadPaperManagementRows()
  expect(rows[0]?.display_title).toBe('Readable Title')
  expect(rows.some((row) => row.ingested === false && row.deletable === false)).toBe(true)
})
```

- [ ] **Step 2: Run the loader test to verify it fails**

Run: `cd frontend; npm run test -- sourceManagementLoader.test.ts`
Expected: FAIL because the management loader does not exist yet.

- [ ] **Step 3: Write failing component tests for grouped render and batch actions**

Use one explicit polling seam in these tests instead of placeholder helpers:

```tsx
function renderWithState(ui: React.ReactElement, stateOverrides: Partial<GlobalState> = {}) {
  const dispatch = vi.fn()
  vi.mocked(useGlobalState).mockReturnValue({
    state: { ...INITIAL_STATE, ...stateOverrides },
    dispatch,
    switchModule: vi.fn(),
  })
  return { dispatch, ...render(ui) }
}

function mockLoadDeleteTaskSequence(...responses: Array<Record<string, unknown>>) {
  const queue = [...responses]
  const last = responses[responses.length - 1]
  vi.mocked(loadDeleteTask).mockImplementation(async () => queue.shift() ?? last)
}
```

```tsx
test('renders ingested and metadata-only paper groups separately', async () => {
  renderWithState(<ImportedSourceManagement />)
  expect(screen.getByText(/Ingested Papers/i)).toBeInTheDocument()
  expect(screen.getByText(/Metadata-only Papers/i)).toBeInTheDocument()
})

test('does not allow metadata-only papers to be selected for deletion', async () => {
  renderWithState(<ImportedSourceManagement />)
  expect(screen.queryByLabelText(/metadata only title/i)).not.toHaveAttribute('type', 'checkbox')
})

test('filters paper rows through the search input across both groups', async () => {
  renderWithState(<ImportedSourceManagement />)
  await user.type(screen.getByPlaceholderText(/search paper/i), 'Attention')
  expect(screen.getByText(/Attention Is All You Need/i)).toBeInTheDocument()
})

test('disables destructive actions while a delete task is active', async () => {
  renderWithState(<ImportedSourceManagement />)
  expect(screen.getByRole('button', { name: /delete selected papers/i })).toBeDisabled()
})

test('submits selected papers separately and renders a partial-success summary', async () => {
  renderWithState(<ImportedSourceManagement />)
  await user.click(screen.getByLabelText(/Attention Is All You Need/i))
  mockLoadDeleteTaskSequence(
    { status: 'queued', progress: 0 },
    { status: 'running', progress: 0.5 },
    { status: 'succeeded', result: { deleted_count: 1, failed_count: 0, skipped_count: 1 } },
  )
  await user.click(screen.getByRole('button', { name: /delete selected papers/i }))
  expect(apiPost).toHaveBeenCalledWith('/tasks/delete/papers', { paper_ids: ['doi:10.1234/attention'], trigger_rebuild: true })
  await waitFor(() => expect(screen.getByText(/1 deleted/i)).toBeInTheDocument())
  expect(screen.getByText(/1 skipped/i)).toBeInTheDocument()
})

test('shows that metadata-only paper rows are not deletable in v1', async () => {
  renderWithState(<ImportedSourceManagement />)
  expect(screen.getByText(/deletion unavailable/i)).toBeInTheDocument()
})

test('submits selected textbooks separately and renders a partial-success summary', async () => {
  renderWithState(<ImportedSourceManagement />)
  await user.click(screen.getByLabelText(/Deep Learning/i))
  mockLoadDeleteTaskSequence(
    { status: 'queued', progress: 0 },
    { status: 'succeeded', result: { deleted_count: 1, failed_count: 0, skipped_count: 1 } },
  )
  await user.click(screen.getByRole('button', { name: /delete selected textbooks/i }))
  expect(apiPost).toHaveBeenCalledWith('/tasks/delete/textbooks', { textbook_ids: ['tb-1'], trigger_rebuild: true })
  await waitFor(() => expect(screen.getByText(/1 deleted/i)).toBeInTheDocument())
  expect(screen.getByText(/1 skipped/i)).toBeInTheDocument()
})

test('refreshes management data and clears removed selections after task completion', async () => {
  renderWithState(<ImportedSourceManagement />)
  await user.click(screen.getByLabelText(/Attention Is All You Need/i))
  mockLoadDeleteTaskSequence(
    { status: 'queued', progress: 0 },
    { status: 'succeeded', result: { deleted_count: 1, failed_count: 0, skipped_count: 0 } },
  )
  await user.click(screen.getByRole('button', { name: /delete selected papers/i }))
  await waitFor(() => expect(screen.queryByLabelText(/Attention Is All You Need/i)).not.toBeInTheDocument())
})

test('clears global selection state and restores the overview graph when batch delete removes the active paper', async () => {
  const { dispatch } = renderWithState(<ImportedSourceManagement />, { activeModule: 'papers', papers: { selectedPaperId: 'doi:10.1234/attention', searchQuery: '' } })
  await user.click(screen.getByLabelText(/Attention Is All You Need/i))
  mockLoadDeleteTaskSequence(
    { status: 'queued', progress: 0 },
    { status: 'succeeded', result: { deleted_count: 1, failed_count: 0, skipped_count: 0 } },
  )
  await user.click(screen.getByRole('button', { name: /delete selected papers/i }))
  await waitFor(() => expect(dispatch).toHaveBeenCalledWith({ type: 'PAPERS_SELECT', paperId: null }))
  expect(loadOverviewGraph).toHaveBeenCalled()
})
```

- [ ] **Step 4: Run the component test to verify it fails**

Run: `cd frontend; npm run test -- importedSourceManagement.test.tsx`
Expected: FAIL because the management component is not implemented yet.

- [ ] **Step 5: Add a light `IngestPage` regression test so the existing upload workflow remains mounted**

```tsx
test('keeps the upload and task controls visible after mounting imported source management', () => {
  localStorage.clear()
  render(
    <MemoryRouter initialEntries={['/ingest']}>
      <IngestPage />
    </MemoryRouter>,
  )
  expect(screen.getByRole('button', { name: /zip/i })).toBeInTheDocument()
  expect(screen.getByRole('link')).toHaveAttribute('href', '/tasks')
})
```

- [ ] **Step 6: Run the `/ingest` regression tests to verify they fail only on missing new behavior**

Run: `cd frontend; npm run test -- importedSourceManagement.test.tsx ingestPage.test.tsx`
Expected: FAIL because the management section and textbook batch flow are not implemented yet, while the existing upload controls remain renderable.

- [ ] **Step 7: Commit the failing `/ingest` management test scaffold**

```bash
git add frontend/tests/sourceManagementLoader.test.ts frontend/tests/importedSourceManagement.test.tsx frontend/tests/ingestPage.test.tsx
git commit -m "test: add imported source management coverage"
```

### Task 7: Implement the `/ingest` management section

**Files:**
- Create: `frontend/src/pages/ImportedSourceManagement.tsx`
- Modify: `frontend/src/pages/IngestPage.tsx`
- Modify: `frontend/src/loaders/sourceManagement.ts`

- [ ] **Step 1: Build the management loader surface**

Add focused functions:

- `loadPaperManagementRows()`
- `loadTextbookManagementRows()`
- `submitPaperDeleteTask()`
- `submitTextbookDeleteTask()`
- `loadDeleteTask(taskId)`

- [ ] **Step 2: Implement grouped paper rendering with readable titles**

Render two sections:

- ingested papers with checkboxes
- metadata-only papers without checkboxes

Always prefer `display_title` in row rendering.

Also render:

- a visible search input for paper rows
- a clear non-destructive status label for metadata-only rows so users can see deletion is unavailable in v1

- [ ] **Step 3: Implement paper search filtering across both paper groups**

The search box should filter by the management row's readable fields:

- `display_title`
- `title`
- `paper_source`
- `doi`
- `paper_id`

- [ ] **Step 4: Implement textbook multi-select rendering**

The textbook block should remain independent from the paper block:

- separate selection state
- separate delete action
- separate summary

- [ ] **Step 5: Add task polling and partial-success summaries**

Show:

- queued/running progress
- `deleted_count`
- `failed_count`
- `skipped_count`
- per-item outcomes if present
- separate paper/textbook result summaries so the two batch flows never share selection or status state by accident

- [ ] **Step 6: Disable destructive actions while delete tasks are active and refresh state after completion**

Make this explicit in the implementation:

- batch delete buttons disable while the current delete task is `queued` or `running`
- after completion, reload paper/textbook management data
- after refresh, clear any selected IDs that no longer exist
- after any successful delete, invalidate `invalidatePaperDataCache()`, `invalidateTextbookCatalogCache()`, `invalidateOverviewGraphCache()`, and `invalidateOverviewStatsCache()`
- if deleted IDs overlap with global `papers.selectedPaperId`, `textbooks.selectedTextbookId`, or `textbooks.selectedChapterId`, clear those global selections; if the active module is showing a now-deleted paper/textbook graph, restore a neutral overview graph instead of leaving ghost nodes onscreen

- [ ] **Step 7: Integrate the management section into `IngestPage.tsx`**

Place it below current import workflows. Keep the edit mount-only from `IngestPage.tsx` and do not break existing upload/task behavior.

- [ ] **Step 8: Run focused frontend verification**

Run: `cd frontend; npm run test -- papersPanelDelete.test.tsx sourceManagementLoader.test.ts importedSourceManagement.test.tsx ingestPage.test.tsx textbooksPanel.test.tsx panelDataLoader.test.ts`
Expected: PASS

- [ ] **Step 9: Run broader frontend verification**

Run: `cd frontend; npm run lint`
Expected: PASS

Run: `cd frontend; npm run build`
Expected: PASS

- [ ] **Step 10: Commit the `/ingest` management UI**

```bash
git add frontend/src/pages/ImportedSourceManagement.tsx frontend/src/pages/IngestPage.tsx frontend/src/loaders/sourceManagement.ts frontend/tests/sourceManagementLoader.test.ts frontend/tests/importedSourceManagement.test.tsx frontend/tests/ingestPage.test.tsx
git commit -m "feat: add imported source management to ingest"
```

### Task 8: Final regression sweep and handoff

**Files:**
- Modify: none expected unless regressions are found

- [ ] **Step 1: Run the end-to-end focused backend regression suite**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_paper_management_api.py tests/test_delete_assets_service.py tests/test_delete_batch_tasks.py tests/test_paper_delete_hard_delete.py tests/test_textbook_graph_api.py`
Expected: PASS

- [ ] **Step 2: Run the end-to-end focused frontend regression suite**

Run: `cd frontend; npm run test -- papersPanelDelete.test.tsx sourceManagementLoader.test.ts importedSourceManagement.test.tsx ingestPage.test.tsx textbooksPanel.test.tsx panelDataLoader.test.ts`
Expected: PASS

- [ ] **Step 3: Refresh docs only if implementation changed the approved design**

If needed:

```bash
git add docs/superpowers/specs/2026-03-11-imported-source-deletion-design.md
git commit -m "docs: align deletion design with implementation details"
```

- [ ] **Step 4: Write execution notes for the next worker**

Include:

- key touched files
- commands already run
- any follow-up risk if a rebuild failure path remains hard to simulate

- [ ] **Step 5: Commit the final implementation batch**

```bash
git status
git add -A
git commit -m "feat: add imported source deletion workflows"
```
