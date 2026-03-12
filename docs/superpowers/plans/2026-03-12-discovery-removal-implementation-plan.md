# Discovery Removal Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the discovery feature end to end, including backend runtime paths, frontend UI, stored graph data, local artifacts, task history, and discovery-specific evaluation code, while preserving one `/discovery -> /ops` frontend redirect for old bookmarks.

**Architecture:** Implement the removal in final-state order but keep the explicit cleanup path alive long enough to purge legacy data first. Start by adding a dedicated cleanup unit plus regression tests, run that cleanup against the local store, then delete backend/runtime code, then remove frontend wiring and update docs, and finish with allowlisted repo-wide verification.

**Tech Stack:** FastAPI, Python, React + Vite + TypeScript, Neo4j, existing task/config storage helpers, pytest, Vitest, ripgrep

---

## File Structure

### Backend

- Create: `backend/scripts/cleanup_discovery.py`
  Thin operator-facing entrypoint that runs discovery cleanup synchronously and exits non-zero on partial failure.
- Modify: `backend/app/ingest/rebuild.py`
  Home for `cleanup_legacy_discovery_artifacts(...)` orchestration and local filesystem cleanup.
- Modify: `backend/app/graph/neo4j_client.py`
  Add low-level discovery graph/schema cleanup helpers and remove discovery-only persistence/query helpers once cleanup is available.
- Modify: `backend/app/tasks/store.py`
  Add or expose a helper seam for scanning/deleting raw persisted task JSON records without relying on `TaskType.discovery_batch`.
- Modify: `backend/app/ops_config_store.py`
  Remove `modules.discovery` from the normalized profile and add a helper seam if needed for stripping legacy config data during cleanup.
- Modify: `backend/app/settings.py`
  Remove `discovery_prompt_policy_path` after the cleanup unit no longer needs the setting.
- Modify: `backend/app/main.py`
  Remove discovery router import/registration and discovery task registration.
- Modify: `backend/app/tasks/models.py`
  Remove `TaskType.discovery_batch`.
- Modify: `backend/app/tasks/handlers.py`
  Remove `handle_discovery_batch` and its imports.
- Modify: `backend/app/api/routers/config_center.py`
  Remove discovery config catalog/profile/assistant behavior and `/config-center/effective/discovery`.
- Modify: `frontend/src/api.ts`
  Remove discovery-specific critical-path probing from the frontend API surface handling.
- Modify: `eval_quality.py`
  Remove only discovery-specific metrics/helpers/CLI output while preserving non-discovery evaluation behavior.
- Delete: `backend/eval_quality.py`
  Discovery-only evaluation helper, if it becomes unused after the shared script is trimmed.
- Delete: `backend/app/api/routers/discovery.py`
- Delete: `backend/app/discovery/__init__.py`
- Delete: `backend/app/discovery/context_builder.py`
- Delete: `backend/app/discovery/evidence_auditor.py`
- Delete: `backend/app/discovery/feedback_service.py`
- Delete: `backend/app/discovery/gap_detector.py`
- Delete: `backend/app/discovery/models.py`
- Delete: `backend/app/discovery/prompt_policy.py`
- Delete: `backend/app/discovery/question_generator.py`
- Delete: `backend/app/discovery/ranker.py`
- Delete: `backend/app/discovery/service.py`
- Create: `backend/tests/test_discovery_cleanup.py`
  Focused cleanup coverage for graph/schema/config/task/filesystem removal and partial-failure reporting.
- Modify: `backend/tests/test_app_main.py`
  Assert discovery routes/task types are gone.
- Modify: `backend/tests/test_config_center_api.py`
  Assert config-center profile/catalog/assistant behavior no longer exposes discovery.
- Delete: `backend/tests/test_discovery_api.py`
- Delete: `backend/tests/test_discovery_context_builder.py`
- Delete: `backend/tests/test_discovery_feedback_loop.py`
- Delete: `backend/tests/test_discovery_gap_detector.py`
- Delete: `backend/tests/test_discovery_gap_text_quality.py`
- Delete: `backend/tests/test_discovery_graph_models.py`
- Delete: `backend/tests/test_discovery_graph_persistence.py`
- Delete: `backend/tests/test_discovery_pipeline.py`
- Delete: `backend/tests/test_discovery_prompt_policy.py`
- Delete: `backend/tests/test_discovery_question_generator.py`
- Delete: `backend/tests/test_eval_discovery_metrics.py`

### Frontend

- Modify: `frontend/src/App.tsx`
  Replace the discovery page route with a redirect to `/ops` and remove discovery workbench UI.
- Modify: `frontend/src/components/TopBar.tsx`
  Remove discovery from module navigation.
- Modify: `frontend/src/panels/OverviewPanel.tsx`
  Remove discovery summary UI and CTA.
- Modify: `frontend/src/loaders/panelData.ts`
  Remove `/discovery/candidates` fetching and related snapshot shape.
- Modify: `frontend/src/pages/ConfigCenterPage.tsx`
  Remove discovery tab, form state, anchors, write-back logic, and stale discovery suggestions from localStorage-backed assistant history.
- Delete: `frontend/src/pages/DiscoveryPage.tsx`
- Delete: `frontend/src/pages/discovery.css`
- Modify: `frontend/tests/panelDataLoader.test.ts`
  Rewrite loader expectations with no discovery fetches.
- Modify: `frontend/tests/workspaceData.test.ts`
  Rewrite overview cache expectations with no discovery snapshot data.
- Create: `frontend/tests/appRoutes.test.tsx`
  Assert `/discovery` redirects to `/ops` and no discovery page path remains.
- Create: `frontend/tests/topBarNavigation.test.tsx`
  Assert discovery no longer appears in top-level navigation.
- Create: `frontend/tests/configCenterPage.test.tsx`
  Assert stored assistant turns do not surface `module: discovery` or `discovery.*` anchors after rollout.

### Docs

- Modify: `README.md`
  Remove discovery as a current feature.
- Modify: `TECHNICAL_OVERVIEW.zh-CN.md`
  Remove discovery as a current capability.
- Create: `docs/superpowers/plans/2026-03-12-discovery-removal-implementation-plan.md`
  This execution plan.

## Chunk 1: Cleanup and Backend Removal

### Task 1: Add failing cleanup and backend-regression tests

**Files:**
- Create: `backend/tests/test_discovery_cleanup.py`
- Modify: `backend/tests/test_app_main.py`
- Modify: `backend/tests/test_config_center_api.py`

- [ ] **Step 1: Write the failing cleanup-unit test for graph/schema/config/task/filesystem coverage**

```python
def test_cleanup_legacy_discovery_artifacts_removes_discovery_residue(monkeypatch, tmp_path):
    report = cleanup_legacy_discovery_artifacts()
    assert report["ok"] is True
    assert report["graph"]["deleted_labels"]["KnowledgeGap"] >= 0
    assert report["tasks"]["deleted_count"] == 1
    assert report["config"]["removed_modules"] == ["discovery"]
    assert report["filesystem"]["legacy_prompt_policy"]["status"] in {"deleted", "missing"}
```

- [ ] **Step 2: Add the partial-failure regression for the cleanup contract**

```python
def test_cleanup_reports_partial_failure_but_continues(monkeypatch):
    report = cleanup_legacy_discovery_artifacts()
    assert report["ok"] is False
    assert report["graph"]["status"] == "error"
    assert report["filesystem"]["status"] == "ok"
```

- [ ] **Step 3: Run the new cleanup tests to verify they fail**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_discovery_cleanup.py`
Expected: FAIL because the cleanup unit and report shape do not exist yet.

- [ ] **Step 4: Rewrite `test_app_main.py` to assert discovery is absent**

```python
def test_register_task_handlers_excludes_discovery_batch():
    register_task_handlers(manager)
    assert TaskType.discovery_batch not in set(manager.registered)

def test_app_does_not_expose_discovery_routes():
    routes = {(route.path, tuple(sorted(route.methods))) for route in app.routes}
    assert ("/discovery/batch", ("POST",)) not in routes
```

- [ ] **Step 5: Rewrite `test_config_center_api.py` to assert discovery is absent from profile/catalog/assistant output**

```python
def test_config_center_profile_roundtrip_without_discovery(monkeypatch, tmp_path):
    profile = client.get("/config-center/profile").json()["profile"]
    assert "discovery" not in profile["modules"]

def test_config_center_catalog_and_assistant_without_discovery(monkeypatch, tmp_path):
    modules = {row["id"]: row for row in catalog["modules"]}
    assert "discovery" not in modules
    assert not any(anchor.startswith("discovery.") for anchor in anchors)
```

- [ ] **Step 6: Run the rewritten backend regression tests to verify they fail**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_app_main.py tests/test_config_center_api.py`
Expected: FAIL because the current app still registers discovery routes, task types, and config fields.

- [ ] **Step 7: Commit the failing-test scaffold**

```bash
git add backend/tests/test_discovery_cleanup.py backend/tests/test_app_main.py backend/tests/test_config_center_api.py
git commit -m "test: add discovery removal cleanup coverage"
```

### Task 2: Implement the cleanup unit and operator script

**Files:**
- Create: `backend/scripts/cleanup_discovery.py`
- Modify: `backend/app/ingest/rebuild.py`
- Modify: `backend/app/graph/neo4j_client.py`
- Modify: `backend/app/tasks/store.py`
- Modify: `backend/app/ops_config_store.py`

- [ ] **Step 1: Add the raw task-history purge helper**

```python
def delete_tasks_by_type_name(type_name: str) -> dict[str, Any]:
    deleted = 0
    for path in tasks_dir().glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if str(payload.get("type") or "").strip() == type_name:
            path.unlink(missing_ok=True)
            deleted += 1
    return {"deleted_count": deleted}
```

- [ ] **Step 2: Add graph/schema cleanup helpers to `Neo4jClient`**

```python
def clear_legacy_discovery_artifacts(self) -> dict[str, Any]:
    return {
        "deleted_labels": {
            "KnowledgeGap": 0,
            "ResearchQuestion": 0,
            "ResearchQuestionCandidate": 0,
            "FeedbackRecord": 0,
            "KnowledgeGapSeed": 0,
        }
    }

def drop_legacy_discovery_schema(self) -> dict[str, int]:
    return {"dropped_constraints": 0, "dropped_indexes": 0}
```

- [ ] **Step 3: Implement legacy prompt-policy path resolution inside `cleanup_legacy_discovery_artifacts(...)`**

```python
def _legacy_discovery_policy_paths() -> list[Path]:
    configured = str(getattr(settings, "discovery_prompt_policy_path", "storage/discovery/prompt_policy_bandit.json") or "").strip()
    raw = Path(configured)
    resolved = raw if raw.is_absolute() else Path(__file__).resolve().parents[2] / raw
    return [resolved]
```

- [ ] **Step 4: Implement the cleanup orchestrator with per-surface status reporting**

```python
def cleanup_legacy_discovery_artifacts(progress=None, log=None) -> dict[str, Any]:
    report = {
        "ok": True,
        "graph": {"status": "pending"},
        "schema": {"status": "pending"},
        "filesystem": {"status": "pending"},
        "config": {"status": "pending"},
        "tasks": {"status": "pending"},
    }
    for key in ("graph", "schema", "filesystem", "config", "tasks"):
        report[key].setdefault("error", None)
    return report
```

- [ ] **Step 5: Add the operator-facing script with non-zero exit on partial failure**

```python
def main() -> int:
    report = cleanup_legacy_discovery_artifacts()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1
```

- [ ] **Step 6: Run the focused cleanup tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_discovery_cleanup.py`
Expected: PASS

- [ ] **Step 7: Run the cleanup script once against the current local store**

Run: `cd backend; .\.venv\Scripts\python.exe scripts/cleanup_discovery.py`
Expected: JSON output with per-surface `status` fields and exit code `0` or `1` depending on actual local residue/failures.

- [ ] **Step 8: Re-run the cleanup script to confirm idempotency**

Run: `cd backend; .\.venv\Scripts\python.exe scripts/cleanup_discovery.py`
Expected: No crash; already-clean surfaces should report `missing`, `deleted_count = 0`, or equivalent no-op output.

- [ ] **Step 9: Commit the cleanup implementation**

```bash
git add backend/scripts/cleanup_discovery.py backend/app/ingest/rebuild.py backend/app/graph/neo4j_client.py backend/app/tasks/store.py backend/app/ops_config_store.py backend/tests/test_discovery_cleanup.py
git commit -m "feat: add legacy discovery cleanup"
```

### Task 3: Remove backend discovery runtime code, config, and evaluation residue

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/tasks/models.py`
- Modify: `backend/app/tasks/handlers.py`
- Modify: `backend/app/ops_config_store.py`
- Modify: `backend/app/api/routers/config_center.py`
- Modify: `backend/app/settings.py`
- Modify: `backend/app/graph/neo4j_client.py`
- Modify: `eval_quality.py`
- Delete: `backend/eval_quality.py`
- Delete: `backend/app/api/routers/discovery.py`
- Delete: `backend/app/discovery/__init__.py`
- Delete: `backend/app/discovery/context_builder.py`
- Delete: `backend/app/discovery/evidence_auditor.py`
- Delete: `backend/app/discovery/feedback_service.py`
- Delete: `backend/app/discovery/gap_detector.py`
- Delete: `backend/app/discovery/models.py`
- Delete: `backend/app/discovery/prompt_policy.py`
- Delete: `backend/app/discovery/question_generator.py`
- Delete: `backend/app/discovery/ranker.py`
- Delete: `backend/app/discovery/service.py`
- Delete: `backend/tests/test_discovery_api.py`
- Delete: `backend/tests/test_discovery_context_builder.py`
- Delete: `backend/tests/test_discovery_feedback_loop.py`
- Delete: `backend/tests/test_discovery_gap_detector.py`
- Delete: `backend/tests/test_discovery_gap_text_quality.py`
- Delete: `backend/tests/test_discovery_graph_models.py`
- Delete: `backend/tests/test_discovery_graph_persistence.py`
- Delete: `backend/tests/test_discovery_pipeline.py`
- Delete: `backend/tests/test_discovery_prompt_policy.py`
- Delete: `backend/tests/test_discovery_question_generator.py`
- Delete: `backend/tests/test_eval_discovery_metrics.py`

- [ ] **Step 1: Remove discovery router/task wiring from `main.py`, `tasks/models.py`, and `tasks/handlers.py`**

```python
def register_task_handlers(manager: TaskManager) -> None:
    manager.register(TaskType.ingest_path, handle_ingest_path)
    manager.register(TaskType.ingest_upload_ready, handle_ingest_upload_ready)
    manager.register(TaskType.upload_replace, handle_upload_replace)
    manager.register(TaskType.delete_papers_batch, handle_delete_papers_batch)
    manager.register(TaskType.delete_textbooks_batch, handle_delete_textbooks_batch)
    manager.register(TaskType.ingest_textbook, handle_ingest_textbook)
```

`TaskType.discovery_batch` and `handle_discovery_batch` should be deleted entirely.

- [ ] **Step 2: Remove discovery config support from `ops_config_store.py`, `config_center.py`, and `settings.py`**

```python
def default_profile() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _now_iso(),
        "modules": {
            "similarity": normalize_similarity_config({}),
        },
    }
```

Delete:

- discovery defaults/normalizers/merge helpers
- `modules.discovery` profile round-tripping
- `/config-center/effective/discovery`
- `Settings.discovery_prompt_policy_path`

- [ ] **Step 3: Remove discovery-owned graph persistence and seed generation**

Delete or trim:

- discovery schema/index creation
- `upsert_discovery_graph(...)`
- discovery listing/query helpers
- `KnowledgeGapSeed` generation during ingest-side claim persistence

```python
def upsert_logic_steps_and_claims(self, paper_id: str, logic: dict, claims: list[dict], step_order: list[str] | None = None) -> None:
    # no discovery seed persistence after claims are written
    return None
```

- [ ] **Step 4: Trim evaluation code instead of deleting unrelated tooling**

Keep non-discovery logic in `eval_quality.py`, but remove only discovery-specific helpers and CLI output:

```python
# delete:
def compute_discovery_metrics(rows: list[dict[str, Any]] | None) -> dict[str, float]:
    return {}
```

Delete `backend/eval_quality.py` only if no non-discovery caller still imports it.

- [ ] **Step 5: Delete the backend discovery package and discovery-only tests**

Use `git rm` so file deletion is explicit and reviewable.

```bash
git rm backend/app/api/routers/discovery.py backend/app/discovery/__init__.py backend/app/discovery/context_builder.py backend/app/discovery/evidence_auditor.py backend/app/discovery/feedback_service.py backend/app/discovery/gap_detector.py backend/app/discovery/models.py backend/app/discovery/prompt_policy.py backend/app/discovery/question_generator.py backend/app/discovery/ranker.py backend/app/discovery/service.py backend/tests/test_discovery_api.py backend/tests/test_discovery_context_builder.py backend/tests/test_discovery_feedback_loop.py backend/tests/test_discovery_gap_detector.py backend/tests/test_discovery_gap_text_quality.py backend/tests/test_discovery_graph_models.py backend/tests/test_discovery_graph_persistence.py backend/tests/test_discovery_pipeline.py backend/tests/test_discovery_prompt_policy.py backend/tests/test_discovery_question_generator.py backend/tests/test_eval_discovery_metrics.py
```

- [ ] **Step 6: Run focused backend tests**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_discovery_cleanup.py tests/test_app_main.py tests/test_config_center_api.py`
Expected: PASS

- [ ] **Step 7: Run a broader backend confidence sweep**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_papers_api.py tests/test_textbook_graph_api.py tests/test_rebuild_cleanup.py`
Expected: PASS

- [ ] **Step 8: Commit the backend removal**

```bash
git add backend/app/main.py backend/app/tasks/models.py backend/app/tasks/handlers.py backend/app/ops_config_store.py backend/app/api/routers/config_center.py backend/app/settings.py backend/app/graph/neo4j_client.py eval_quality.py
git commit -m "refactor: remove discovery backend runtime"
```

## Chunk 2: Frontend Removal, Docs, and Verification

### Task 4: Add failing frontend regression tests for loader, routing, and navigation cleanup

**Files:**
- Modify: `frontend/tests/panelDataLoader.test.ts`
- Modify: `frontend/tests/workspaceData.test.ts`
- Create: `frontend/tests/appRoutes.test.tsx`
- Create: `frontend/tests/topBarNavigation.test.tsx`
- Create: `frontend/tests/configCenterPage.test.tsx`

- [ ] **Step 1: Rewrite the loader tests so overview no longer depends on discovery candidates**

```ts
test('caches overview stats without discovery fetches', async () => {
  const first = await loadOverviewStatsSnapshot()
  expect(first.paperCount).toBe(2)
  expect(vi.mocked(apiGet)).toHaveBeenCalledTimes(1)
})
```

- [ ] **Step 2: Rewrite the workspace cache test with no `discoveryItems` expectations**

```ts
test('forces a refresh when requested explicitly', async () => {
  const third = await loadOverviewStatsSnapshot()
  expect(third.paperCount).toBe(3)
  expect('discoveryItems' in third).toBe(false)
})
```

- [ ] **Step 3: Add the failing router redirect test**

```tsx
test('redirects /discovery to /ops', async () => {
  render(<MemoryRouter initialEntries={['/discovery']}><App /></MemoryRouter>)
  expect(await screen.findByText(/operations workbench/i)).toBeInTheDocument()
})
```

- [ ] **Step 4: Add the failing top-bar regression test**

```tsx
test('top bar does not show discovery navigation', () => {
  render(<TopBar />)
  expect(screen.queryByText(/discovery/i)).not.toBeInTheDocument()
})
```

- [ ] **Step 5: Add the failing Config Center assistant-history regression test**

```tsx
test('filters discovery suggestions from stored assistant turns', async () => {
  window.localStorage.setItem('logickg.config.assistant.turns', JSON.stringify([
    { id: 't1', suggestions: [{ module: 'discovery', anchor: 'discovery.max_gaps', title: 'old' }] },
  ]))
  render(<ConfigCenterPage />)
  expect(screen.queryByText(/old/i)).not.toBeInTheDocument()
})
```

- [ ] **Step 6: Run the frontend regression tests to verify they fail**

Run: `cd frontend; npm run test -- panelDataLoader.test.ts workspaceData.test.ts appRoutes.test.tsx topBarNavigation.test.tsx configCenterPage.test.tsx`
Expected: FAIL because the current app still fetches discovery data, renders discovery UI, and retains discovery suggestions in stored assistant turns.

- [ ] **Step 7: Commit the failing frontend-test scaffold**

```bash
git add frontend/tests/panelDataLoader.test.ts frontend/tests/workspaceData.test.ts frontend/tests/appRoutes.test.tsx frontend/tests/topBarNavigation.test.tsx frontend/tests/configCenterPage.test.tsx
git commit -m "test: add discovery removal frontend coverage"
```

### Task 5: Remove frontend discovery wiring and keep the redirect

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/TopBar.tsx`
- Modify: `frontend/src/panels/OverviewPanel.tsx`
- Modify: `frontend/src/loaders/panelData.ts`
- Modify: `frontend/src/pages/ConfigCenterPage.tsx`
- Modify: `frontend/src/api.ts`
- Delete: `frontend/src/pages/DiscoveryPage.tsx`
- Delete: `frontend/src/pages/discovery.css`
- Modify: `frontend/tests/panelDataLoader.test.ts`
- Modify: `frontend/tests/workspaceData.test.ts`
- Modify: `frontend/tests/appRoutes.test.tsx`
- Modify: `frontend/tests/topBarNavigation.test.tsx`
- Modify: `frontend/tests/configCenterPage.test.tsx`

- [ ] **Step 1: Remove discovery fetches and snapshot fields from `panelData.ts`**

```ts
export type OverviewStatsSnapshot = {
  paperCount: number
}

export async function loadOverviewStatsSnapshot(options: LoadOptions = {}) {
  const paperRes = await apiGet<{ papers: unknown[] }>('/graph/papers?limit=1000')
  return { paperCount: Array.isArray(paperRes.papers) ? paperRes.papers.length : 0 }
}
```

- [ ] **Step 2: Remove discovery UI from `OverviewPanel.tsx`**

Delete:

- discovery summary state
- discovery quality summary memo
- discovery CTA card/button

Keep:

- paper stats
- ingest quick actions
- graph/stat refresh buttons

- [ ] **Step 3: Replace the discovery page route with an intentional redirect in `App.tsx`**

```tsx
<Route path="/discovery" element={<Navigate to="/ops" replace />} />
```

Also remove:

- `DiscoveryPage` import
- discovery workbench button in the shell bar

- [ ] **Step 4: Remove discovery from `TopBar.tsx`, `ConfigCenterPage.tsx`, and `api.ts`**

Examples:

```ts
const MODULES = [
  { id: 'overview', moduleId: 'overview', label: { zh: '总览', en: 'Overview' }, note: { zh: '全局知识图谱', en: 'Global KG' } },
  { id: 'papers', moduleId: 'papers', label: { zh: '论文', en: 'Papers' }, note: { zh: '引文网络', en: 'Citation Net' } },
  { id: 'ask', moduleId: 'ask', label: { zh: '问答', en: 'Ask' }, note: { zh: '图谱增强问答', en: 'GraphRAG' } },
  { id: 'textbooks', moduleId: 'textbooks', label: { zh: '教材', en: 'Textbooks' }, note: { zh: '知识结构', en: 'Knowledge Base' } },
  { id: 'ops', href: '/ops', label: { zh: '运维', en: 'Ops' }, note: { zh: '任务与配置', en: 'Tasks & Config' } },
]
```

```ts
const CRITICAL_API_PATH_PREFIXES = ['/graph/network', '/graph/papers', '/rag/ask_v2', '/textbooks', '/config-center']
```

`ConfigCenterPage.tsx` must remove:

- `DiscoveryConfig`
- discovery tab selection
- discovery field rendering
- discovery anchor-update branches
- stored assistant suggestions whose `module` is `discovery` or whose `anchor` starts with `discovery.`

Example filter seam:

```ts
function sanitizeAssistantTurns(turns: AssistantTurn[]): AssistantTurn[] {
  return turns
    .map((turn) => ({
      ...turn,
      suggestions: turn.suggestions.filter((row) => row.module !== 'discovery' && !String(row.anchor ?? '').startsWith('discovery.')),
    }))
    .filter((turn) => turn.suggestions.length > 0 || turn.error || turn.goal)
}
```

- [ ] **Step 5: Delete the page and stylesheet files**

```bash
git rm frontend/src/pages/DiscoveryPage.tsx frontend/src/pages/discovery.css
```

- [ ] **Step 6: Run focused frontend tests**

Run: `cd frontend; npm run test -- panelDataLoader.test.ts workspaceData.test.ts appRoutes.test.tsx topBarNavigation.test.tsx configCenterPage.test.tsx`
Expected: PASS

- [ ] **Step 7: Run frontend lint and a broader regression sweep**

Run: `cd frontend; npm run lint`
Expected: PASS

Run: `cd frontend; npm run test -- overviewLoader.test.ts tasksPage.test.tsx rightPanelAskSummary.test.tsx`
Expected: PASS

- [ ] **Step 8: Commit the frontend removal**

```bash
git add frontend/src/App.tsx frontend/src/components/TopBar.tsx frontend/src/panels/OverviewPanel.tsx frontend/src/loaders/panelData.ts frontend/src/pages/ConfigCenterPage.tsx frontend/src/api.ts frontend/tests/panelDataLoader.test.ts frontend/tests/workspaceData.test.ts frontend/tests/appRoutes.test.tsx frontend/tests/topBarNavigation.test.tsx frontend/tests/configCenterPage.test.tsx
git commit -m "refactor: remove discovery frontend surfaces"
```

### Task 6: Update active docs and run final repo verification

**Files:**
- Modify: `README.md`
- Modify: `TECHNICAL_OVERVIEW.zh-CN.md`

- [ ] **Step 1: Update active docs so discovery is no longer described as a live feature**

```md
- remove Discovery from feature lists, workflows, and screenshots/copy references
- keep historical docs/specs untouched
```

- [ ] **Step 2: Run the cleanup script one final time after code removal**

Run: `cd backend; .\.venv\Scripts\python.exe scripts/cleanup_discovery.py`
Expected: No crash; output should report no remaining discovery residue or explicit no-op counts.

- [ ] **Step 3: Run the backend verification bundle**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_discovery_cleanup.py tests/test_app_main.py tests/test_config_center_api.py tests/test_papers_api.py tests/test_textbook_graph_api.py tests/test_rebuild_cleanup.py`
Expected: PASS

- [ ] **Step 4: Run the frontend verification bundle**

Run: `cd frontend; npm run lint`
Expected: PASS

Run: `cd frontend; npm run test`
Expected: PASS

- [ ] **Step 5: Run allowlisted grep checks over live code paths**

Run:

```bash
rg -n "app\\.discovery|TaskType\\.discovery_batch|handle_discovery_batch|modules\\.discovery|discovery_prompt_policy_path|upsert_discovery_graph" backend frontend README.md TECHNICAL_OVERVIEW.zh-CN.md eval_quality.py
```

Expected: no matches

Run:

```bash
rg -n "\"/discovery\"|'/discovery'|/discovery" frontend/src frontend/tests
```

Expected: exactly one intentional redirect path in `frontend/src/App.tsx`, plus redirect-specific test assertions only

- [ ] **Step 6: Spot-check local residue under the active storage root**

Run:

```bash
cd backend; .\.venv\Scripts\python.exe -c "from app.tasks.store import tasks_dir; from app.ingest.rebuild import _storage_dir; import json; task_hits=[str(p) for p in tasks_dir().glob('*.json') if str(json.loads(p.read_text(encoding='utf-8')).get('type') or '') == 'discovery_batch']; artifact_hits=[str(p) for p in _storage_dir().rglob('*') if p.is_file() and 'discovery' in p.name.lower()]; print('TASK_HITS', task_hits); print('ARTIFACT_HITS', artifact_hits)"
```

Expected: no `discovery_batch` task files and no discovery-only prompt-policy/artifact files remain

- [ ] **Step 7: Commit the docs and verification-driven cleanup**

```bash
git add README.md TECHNICAL_OVERVIEW.zh-CN.md
git commit -m "docs: remove discovery from active product docs"
```
