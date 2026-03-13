# Paper Graph and Textbook Upload Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate recursive textbook upload workflow inside `/ingest` and redesign the paper detail graph into a readable clustered workbench with clickable node detail cards.

**Architecture:** Keep one `/ingest` page but split it into independent paper and textbook import work areas. Implement textbook upload as a parallel upload/session/scan/commit pipeline under `backend/app/ingest/`, reusing the existing single-textbook ingestion pipeline at commit time. Redesign the paper detail graph as a structured preview: clustered zones, overflow summary nodes, and a fixed right-side detail card instead of a one-line footer hint.

**Tech Stack:** FastAPI, Python task handlers, existing chunked upload helpers, React + Vite, Vitest, Cytoscape, shared `ui.css`, `@superpowers:test-driven-development`, `@superpowers:systematic-debugging`, `@superpowers:verification-before-completion`

---

## File Map

### Backend

- Create: `backend/app/ingest/textbook_identity.py`
  Shared helper for inferred title normalization, content fingerprinting, and derived `textbook_id`.
- Create: `backend/app/ingest/textbook_upload_store.py`
  Textbook upload session persistence, staged file bookkeeping, and scan-cache read/write.
- Create: `backend/app/ingest/scan_textbook_upload.py`
  Recursive textbook unit detection, subtree validation, title inference, conflict marking, and scan summary generation.
- Create: `backend/app/ingest/textbook_upload_actions.py`
  Skip and commit helpers for textbook upload sessions.
- Modify: `backend/app/ingest/textbook_pipeline.py`
  Reuse the new textbook identity helper so single-textbook and upload-batch ingestion share the same ID logic.
- Modify: `backend/app/api/routers/textbooks.py`
  Add `/textbooks/upload/*` endpoints and keep existing single-file `/textbooks/ingest`.
- Modify: `backend/app/tasks/models.py`
  Add `ingest_textbook_upload_ready`.
- Modify: `backend/app/tasks/handlers.py`
  Add the batch textbook upload commit handler that reuses `ingest_textbook(...)`.
- Test: `backend/tests/test_textbook_identity.py`
- Test: `backend/tests/test_scan_textbook_upload.py`
- Test: `backend/tests/test_textbook_upload_actions.py`
- Test: `backend/tests/test_textbooks_upload_api.py`

### Frontend

- Modify: `frontend/src/pages/IngestPage.tsx`
  Add a dedicated textbook upload work area with separate state, summaries, scan list, skip action, and batch commit action.
- Modify: `frontend/src/pages/PaperDetailPage.tsx`
  Add graph overflow preview rules, a right-side detail card, and Chinese copy cleanup for the touched graph summary surface.
- Modify: `frontend/src/components/SignalGraph.tsx`
  Add clustered-island visual styling with constrained zones and summary-node-friendly rendering.
- Modify: `frontend/src/styles/ui.css`
  Add textbook upload section styling and paper graph workbench/detail-card styling.
- Test: `frontend/tests/ingestTextbookUpload.test.tsx`
- Test: `frontend/tests/paperDetailGraph.test.tsx`
- Modify: `frontend/tests/ingestPage.test.tsx`

### Notes

- The worktree is already dirty. Each commit in this plan must stage only the files listed in that task.
- Do not rewrite unrelated discovery-removal work while implementing this plan.

## Chunk 1: Textbook Upload Workflow

### Task 1: Extract Shared Textbook Identity Helpers

**Files:**
- Create: `backend/app/ingest/textbook_identity.py`
- Modify: `backend/app/ingest/textbook_pipeline.py`
- Test: `backend/tests/test_textbook_identity.py`

- [ ] **Step 1: Write the failing backend identity tests**

```python
from app.ingest.textbook_identity import infer_textbook_identity


def test_infer_textbook_identity_prefers_h1_title(tmp_path):
    md = tmp_path / 'book.md'
    md.write_text('# 粉体力学基础\n\n内容', encoding='utf-8')

    identity = infer_textbook_identity(md)

    assert identity.inferred_title == '粉体力学基础'
    assert identity.textbook_id.startswith('tb:')


def test_infer_textbook_identity_falls_back_to_filename(tmp_path):
    md = tmp_path / 'chapter_notes.md'
    md.write_text('无标题正文', encoding='utf-8')

    identity = infer_textbook_identity(md)

    assert identity.inferred_title == 'chapter_notes'
```

- [ ] **Step 2: Run the identity tests to verify they fail**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_textbook_identity.py`

Expected: FAIL with import error or missing helper assertions.

- [ ] **Step 3: Implement the minimal shared identity helper**

```python
@dataclass(frozen=True)
class TextbookIdentity:
    inferred_title: str
    normalized_title: str
    content_fingerprint: str
    textbook_id: str


def infer_textbook_identity(md_path: Path) -> TextbookIdentity:
    text = md_path.read_text(encoding='utf-8', errors='replace')
    inferred_title = _infer_title_from_markdown(text, md_path)
    fingerprint = _fingerprint_text(text)
    textbook_id = _textbook_id_from_title_and_fingerprint(inferred_title, fingerprint)
    return TextbookIdentity(inferred_title, _normalize_title(inferred_title), fingerprint, textbook_id)
```

- [ ] **Step 4: Rewire the single-textbook pipeline to reuse the helper**

```python
identity = infer_textbook_identity(Path(md_path))
title = str(metadata.get('title') or identity.inferred_title)
tb_id = textbook_id_for_ingest(title=title, fingerprint=identity.content_fingerprint)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_textbook_identity.py`

Expected: PASS

- [ ] **Step 6: Commit only the identity work**

```powershell
git add -- backend/app/ingest/textbook_identity.py backend/app/ingest/textbook_pipeline.py backend/tests/test_textbook_identity.py
git commit -m "feat: share textbook identity inference"
```

### Task 2: Build Recursive Textbook Upload Scanning

**Files:**
- Create: `backend/app/ingest/textbook_upload_store.py`
- Create: `backend/app/ingest/scan_textbook_upload.py`
- Test: `backend/tests/test_scan_textbook_upload.py`

- [ ] **Step 1: Write failing recursive scan tests**

```python
def test_scan_textbook_upload_detects_multiple_nested_textbooks(tmp_path):
    root = tmp_path / 'uploads'
    (root / 'set-a' / 'book-1').mkdir(parents=True)
    (root / 'set-b' / 'deep' / 'book-2' / 'images').mkdir(parents=True)
    (root / 'set-a' / 'book-1' / 'main.md').write_text('# 教材一\n\n正文', encoding='utf-8')
    (root / 'set-b' / 'deep' / 'book-2' / 'main.md').write_text('# 教材二\n\n正文', encoding='utf-8')

    scan = scan_textbook_tree(root)

    assert [unit.title for unit in scan.units] == ['教材一', '教材二']


def test_scan_textbook_upload_ignores_multi_markdown_parent_until_child_unit(tmp_path):
    root = tmp_path / 'bundle'
    (root / 'parent' / 'book-a').mkdir(parents=True)
    (root / 'parent' / 'book-b').mkdir(parents=True)
    (root / 'parent' / 'book-a' / 'main.md').write_text('# A', encoding='utf-8')
    (root / 'parent' / 'book-b' / 'main.md').write_text('# B', encoding='utf-8')

    scan = scan_textbook_tree(root)

    assert len(scan.units) == 2
```

- [ ] **Step 2: Run the recursive scan tests to verify they fail**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_scan_textbook_upload.py`

Expected: FAIL with missing scan/store modules.

- [ ] **Step 3: Implement textbook upload session storage**

```python
@dataclass
class TextbookUploadState:
    upload_id: str
    root: str
    units: list[dict[str, Any]]
    skipped_unit_ids: set[str]


def start_textbook_upload(mode: str) -> str: ...
def finish_textbook_upload(upload_id: str) -> dict[str, Any]: ...
def save_textbook_scan(upload_id: str, payload: dict[str, Any]) -> None: ...
```

- [ ] **Step 4: Implement recursive subtree-based scan logic**

```python
def detect_textbook_units(root: Path) -> list[DetectedTextbookUnit]:
    subtree_md_count = _count_markdown_files_per_directory(root)
    candidates = _collect_single_markdown_candidates(root, subtree_md_count)
    return _select_highest_valid_candidates(candidates, subtree_md_count)
```

- [ ] **Step 5: Include title inference, asset counts, and conflict marking in scan results**

```python
identity = infer_textbook_identity(main_md_path)
status = 'conflict' if existing_textbook(identity.textbook_id) else 'ready'
unit = {
    'unit_id': unit_id,
    'unit_rel_dir': rel_dir,
    'main_md_rel_path': rel_md_path,
    'title': identity.inferred_title,
    'textbook_id': identity.textbook_id,
    'asset_count': asset_count,
    'status': status,
}
```

- [ ] **Step 6: Run the recursive scan tests to verify they pass**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_scan_textbook_upload.py tests/test_textbook_identity.py`

Expected: PASS

- [ ] **Step 7: Commit only the scan/store work**

```powershell
git add -- backend/app/ingest/textbook_upload_store.py backend/app/ingest/scan_textbook_upload.py backend/tests/test_scan_textbook_upload.py backend/tests/test_textbook_identity.py
git commit -m "feat: add recursive textbook upload scanning"
```

### Task 3: Add Textbook Upload APIs and Batch Commit Task

**Files:**
- Create: `backend/app/ingest/textbook_upload_actions.py`
- Modify: `backend/app/api/routers/textbooks.py`
- Modify: `backend/app/tasks/models.py`
- Modify: `backend/app/tasks/handlers.py`
- Test: `backend/tests/test_textbook_upload_actions.py`
- Test: `backend/tests/test_textbooks_upload_api.py`

- [ ] **Step 1: Write failing skip/commit/API tests**

```python
def test_skip_textbook_unit_marks_unit_skipped(client, prepared_upload):
    response = client.post('/textbooks/upload/skip', json={'upload_id': prepared_upload, 'unit_id': 'tb-unit-1'})
    assert response.status_code == 200
    assert response.json()['units'][0]['status'] == 'skipped'


def test_commit_ready_textbook_upload_submits_batch_task(client, prepared_upload):
    response = client.post('/textbooks/upload/commit_ready', json={'upload_id': prepared_upload})
    assert response.status_code == 200
    assert response.json()['task_id']
```

- [ ] **Step 2: Run the upload action/API tests to verify they fail**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_textbook_upload_actions.py tests/test_textbooks_upload_api.py`

Expected: FAIL with missing endpoints/task type/action helpers.

- [ ] **Step 3: Implement skip and commit helpers**

```python
def skip_textbook_unit(upload_id: str, unit_id: str) -> dict[str, Any]:
    scan = load_textbook_scan(upload_id)
    updated = _mark_unit_skipped(scan, unit_id)
    save_textbook_scan(upload_id, updated)
    return updated


def commit_ready_textbook_units(upload_id: str) -> list[dict[str, Any]]:
    scan = load_textbook_scan(upload_id)
    return [unit for unit in scan['units'] if unit['status'] == 'ready']
```

- [ ] **Step 4: Add `/textbooks/upload/*` endpoints**

```python
@router.post('/upload/start')
def start_textbook_upload(...): ...

@router.post('/upload/finish')
def finish_textbook_upload(...): ...

@router.post('/upload/skip')
def skip_textbook_upload_unit(...): ...

@router.post('/upload/commit_ready')
def commit_ready_textbooks(...): ...
```

- [ ] **Step 5: Add the batch task type and handler**

```python
class TaskType(str, Enum):
    ingest_textbook_upload_ready = 'ingest_textbook_upload_ready'


def handle_ingest_textbook_upload_ready(...):
    for unit in ready_units:
        result = ingest_textbook(unit['staged_main_md_path'], metadata={'title': unit['title']}, progress=progress, log=log)
```

- [ ] **Step 6: Run the backend upload action/API tests to verify they pass**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_textbook_upload_actions.py tests/test_textbooks_upload_api.py tests/test_scan_textbook_upload.py`

Expected: PASS

- [ ] **Step 7: Commit only the textbook upload API/task work**

```powershell
git add -- backend/app/ingest/textbook_upload_actions.py backend/app/api/routers/textbooks.py backend/app/tasks/models.py backend/app/tasks/handlers.py backend/tests/test_textbook_upload_actions.py backend/tests/test_textbooks_upload_api.py
git commit -m "feat: add textbook upload batch ingestion"
```

### Task 4: Add the Textbook Upload Section to `/ingest`

**Files:**
- Modify: `frontend/src/pages/IngestPage.tsx`
- Test: `frontend/tests/ingestTextbookUpload.test.tsx`
- Modify: `frontend/tests/ingestPage.test.tsx`

- [ ] **Step 1: Write failing frontend tests for the separate textbook section**

```tsx
test('renders separate paper and textbook import sections', async () => {
  render(<IngestPage />)

  expect(screen.getByText('论文导入')).toBeInTheDocument()
  expect(screen.getByText('教材导入')).toBeInTheDocument()
})


test('renders detected textbook units and allows skip', async () => {
  mockApiSequenceForTextbookScan()
  render(<IngestPage />)

  expect(await screen.findByText('教材一')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '跳过' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the frontend textbook upload tests to verify they fail**

Run: `cd frontend; npm run test -- ingestTextbookUpload.test.tsx ingestPage.test.tsx`

Expected: FAIL because the textbook upload section does not exist yet.

- [ ] **Step 3: Implement textbook upload state and transport flow in `IngestPage.tsx`**

```tsx
const [textbookUploadId, setTextbookUploadId] = useState('')
const [textbookScan, setTextbookScan] = useState<TextbookUploadScan | null>(null)
const [textbookTaskId, setTextbookTaskId] = useState('')

async function submitTextbookZip() { ... }
async function submitTextbookFolder() { ... }
async function skipTextbookUnit(unitId: string) { ... }
async function commitReadyTextbooks() { ... }
```

- [ ] **Step 4: Render textbook-specific summaries and scan rows**

```tsx
<section className="panel ingestTextbookPanel">
  <div className="panelTitle">教材导入</div>
  <TextbookUploadSummary scan={textbookScan} task={textbookTask} />
  <TextbookUploadResults scan={textbookScan} onSkip={skipTextbookUnit} />
</section>
```

- [ ] **Step 5: Run the frontend tests to verify they pass**

Run: `cd frontend; npm run test -- ingestTextbookUpload.test.tsx ingestPage.test.tsx`

Expected: PASS

- [ ] **Step 6: Commit only the textbook ingest-page UI work**

```powershell
git add -- frontend/src/pages/IngestPage.tsx frontend/tests/ingestTextbookUpload.test.tsx frontend/tests/ingestPage.test.tsx
git commit -m "feat: add textbook upload section to ingest page"
```

## Chunk 2: Paper Detail Graph Workbench

### Task 5: Lock Down the New Paper Graph Preview Model

**Files:**
- Modify: `frontend/src/pages/PaperDetailPage.tsx`
- Test: `frontend/tests/paperDetailGraph.test.tsx`

- [ ] **Step 1: Write failing tests for overflow nodes and detail-card meta**

```tsx
test('shows a detail card when a graph node is selected', async () => {
  renderPaperDetailWithDenseGraph()

  await user.click(screen.getByText('实验逻辑'))

  expect(screen.getByText('节点详情')).toBeInTheDocument()
  expect(screen.getByText('逻辑步骤')).toBeInTheDocument()
})


test('collapses overflow citations into a summary node', async () => {
  renderPaperDetailWithManyCitations()

  expect(screen.getByText(/更多引文 \+\d+/)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the paper graph tests to verify they fail**

Run: `cd frontend; npm run test -- paperDetailGraph.test.tsx`

Expected: FAIL because the current graph preview and detail surface do not expose these behaviors.

- [ ] **Step 3: Implement capped clustered graph preview building in `PaperDetailPage.tsx`**

```tsx
const MAX_CITATION_PREVIEW = 10
const MAX_CLAIMS_PER_STEP = 8

function buildOverflowNode(id: string, title: string, detail: string, tab: PaperTab): SignalGraphNode { ... }
```

- [ ] **Step 4: Implement the fixed detail card model**

```tsx
const selectedGraphMeta = paperGraph.metaMap.get(selectedGraphNodeId) ?? emptyGraphMeta

<aside className="paperGraphDetailCard">
  <div className="kicker">节点详情</div>
  <div className="paperGraphDetailTitle">{selectedGraphMeta.title}</div>
  <div className="metaLine">{selectedGraphMeta.typeLabel}</div>
  <div className="paperGraphDetailBody">{selectedGraphMeta.detail}</div>
</aside>
```

- [ ] **Step 5: Run the paper graph tests to verify they pass**

Run: `cd frontend; npm run test -- paperDetailGraph.test.tsx`

Expected: PASS

- [ ] **Step 6: Commit only the paper preview-model work**

```powershell
git add -- frontend/src/pages/PaperDetailPage.tsx frontend/tests/paperDetailGraph.test.tsx
git commit -m "feat: add paper graph detail card and overflow nodes"
```

### Task 6: Redesign `SignalGraph` into a Clustered-Island Preview

**Files:**
- Modify: `frontend/src/components/SignalGraph.tsx`
- Modify: `frontend/src/styles/ui.css`
- Test: `frontend/tests/paperDetailGraph.test.tsx`

- [ ] **Step 1: Extend the failing tests to check graph-zone styling hooks**

```tsx
test('renders clustered graph workbench classes', async () => {
  renderPaperDetailWithDenseGraph()
  expect(document.querySelector('.paperGraphWorkbench')).not.toBeNull()
})
```

- [ ] **Step 2: Run the graph tests to verify they still fail for the styling/layout gap**

Run: `cd frontend; npm run test -- paperDetailGraph.test.tsx`

Expected: FAIL until the new workbench structure and classes exist.

- [ ] **Step 3: Replace the flat preset layout with constrained clustered zones**

```tsx
function buildPaperClusterPositions(...) {
  return {
    root: topCenter,
    logic: middleArc,
    claims: groupedClaimGrid,
    citations: rightIsland,
  }
}
```

- [ ] **Step 4: Update node and edge styling toward the approved B direction**

```tsx
{
  selector: 'node[kind = "citation"]',
  style: {
    shape: 'roundrectangle',
    width: 84,
    height: 24,
    'background-color': 'rgba(242, 186, 117, 0.92)',
  },
}
```

- [ ] **Step 5: Add responsive workbench and detail-card CSS**

```css
.paperGraphWorkbench { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.8fr); gap: 18px; }
.paperGraphDetailCard { position: sticky; top: 18px; }
@media (max-width: 1100px) { .paperGraphWorkbench { grid-template-columns: 1fr; } }
```

- [ ] **Step 6: Run the graph tests to verify they pass**

Run: `cd frontend; npm run test -- paperDetailGraph.test.tsx`

Expected: PASS

- [ ] **Step 7: Commit only the graph-style work**

```powershell
git add -- frontend/src/components/SignalGraph.tsx frontend/src/styles/ui.css frontend/tests/paperDetailGraph.test.tsx frontend/src/pages/PaperDetailPage.tsx
git commit -m "feat: redesign paper detail graph workbench"
```

### Task 7: Normalize Touched Chinese Copy and Run Verification

**Files:**
- Modify: `frontend/src/pages/PaperDetailPage.tsx`
- Modify: `frontend/src/pages/IngestPage.tsx`
- Test: `frontend/tests/ingestTextbookUpload.test.tsx`
- Test: `frontend/tests/paperDetailGraph.test.tsx`

- [ ] **Step 1: Add failing assertions for touched Chinese copy**

```tsx
test('paper detail graph summary uses Chinese labels', async () => {
  renderPaperDetailWithDenseGraph()
  expect(screen.getByText('节点详情')).toBeInTheDocument()
  expect(screen.getByText('覆盖概览')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the frontend tests to verify the copy assertions fail if labels are still mixed**

Run: `cd frontend; npm run test -- ingestTextbookUpload.test.tsx paperDetailGraph.test.tsx`

Expected: FAIL if English labels remain in the touched surfaces.

- [ ] **Step 3: Normalize the remaining touched copy**

```tsx
<div className="kicker">覆盖概览</div>
<div className="metaLine">{reviewNeedsReview ? '待人工复核' : '暂无待复核项'}</div>
```

- [ ] **Step 4: Run focused verification**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_textbook_identity.py tests/test_scan_textbook_upload.py tests/test_textbook_upload_actions.py tests/test_textbooks_upload_api.py`

Expected: PASS

Run: `cd frontend; npm run test -- ingestTextbookUpload.test.tsx ingestPage.test.tsx paperDetailGraph.test.tsx`

Expected: PASS

Run: `cd frontend; npm run lint`

Expected: PASS

- [ ] **Step 5: Run broader regression verification**

Run: `cd frontend; npm run build`

Expected: PASS

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q tests/test_paper_management_api.py tests/test_textbook_graph_api.py`

Expected: PASS

- [ ] **Step 6: Commit only the verification-safe final polish**

```powershell
git add -- frontend/src/pages/PaperDetailPage.tsx frontend/src/pages/IngestPage.tsx frontend/tests/ingestTextbookUpload.test.tsx frontend/tests/paperDetailGraph.test.tsx
git commit -m "fix: finalize textbook upload and paper graph polish"
```

