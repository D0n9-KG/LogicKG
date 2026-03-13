# Paper Graph and Textbook Upload Design

## Goal

Deliver two user-facing improvements that work together cleanly in the current workspace:

- add a separate `教材导入` flow inside `/ingest`
- let textbook import use `文件夹 / ZIP` uploads instead of manual path + metadata entry
- support recursive detection of multiple textbook units inside a large nested folder
- keep paper import and textbook import clearly separated in the UI
- fix the paper detail graph so clicking a node shows stable, readable node information
- redesign the paper detail graph so it is less flat, less crowded, and less prone to node overlap
- keep Chinese UI copy consistent where English is not required

## Existing Context

The current codebase already has part of the required behavior, but the missing pieces are split across backend and frontend.

- `frontend/src/pages/IngestPage.tsx` currently exposes only the paper upload flow plus imported-source management
- `backend/app/api/routers/textbooks.py` currently exposes `POST /textbooks/ingest`, but it only accepts a single Markdown file path with hand-entered metadata
- `backend/app/ingest/textbook_pipeline.py` already contains the actual textbook ingestion pipeline once a single textbook Markdown path is known
- `backend/app/ingest/textbook_splitter.py` already splits one textbook Markdown file into chapters
- `frontend/src/pages/PaperDetailPage.tsx` already keeps graph selection state and passes `selectedId` plus `onSelect` into `SignalGraph`
- `frontend/src/components/SignalGraph.tsx` already emits node selection on click and can apply selected/faded states

This means the paper graph problem is not that click events are entirely missing. The current page already receives selection updates, but the user-visible feedback is too weak:

- node details are reduced to a small one-line hint below the graph
- the graph preview currently tries to show too many claim and citation nodes at once
- the current preset layout is readable only at modest node counts and becomes crowded when citations and claims grow
- the node shapes and edge treatment feel visually flat for a detail-page workbench

The textbook import problem is similar: the backend can ingest one textbook once it has a Markdown file path, but the frontend has no upload-first workflow comparable to paper import, and the backend has no recursive upload scanning model for textbook batches.

## Approved Scope

### In scope

- a separate `教材导入` block inside `/ingest`
- keep `论文导入` and `教材导入` as two distinct sections on the same page
- textbook upload via `ZIP` and `文件夹`
- recursive textbook unit detection inside nested upload trees
- a scan/review/commit flow for textbook uploads, similar in spirit to paper import
- per-textbook skip support before commit
- partial-success textbook batch import behavior
- paper detail graph visual redesign
- paper detail graph node-style redesign
- paper detail graph overlap reduction through layout and preview summarization
- a fixed right-side node detail card in the paper detail view
- Chinese copy normalization for the touched paper detail and ingest surfaces

### Out of scope

- keeping the manual textbook metadata form as the primary import experience
- textbook conflict replacement or merge workflows in v1
- generic graph-component redesign across the whole application
- textbook source-file deletion outside the existing textbook delete behavior
- rewriting the full paper detail page outside the graph workbench area
- free-layout graph exploration with arbitrary drag-first editing behavior

## Key Decisions

### 1. Keep one ingest page, but split paper and textbook import into separate work areas

`/ingest` should remain the unified import center, but `论文导入` and `教材导入` must be visually and behaviorally separated.

This keeps the user workflow simple:

- one place to go for import-related work
- one block for paper-specific scanning, DOI handling, and conflict resolution
- one block for textbook-specific recursive detection and batch import

This also matches the user preference that textbook import should feel like paper import, not like an admin form.

### 2. Textbook import becomes upload-first, not metadata-form-first

The current `POST /textbooks/ingest` contract assumes the user already knows:

- the Markdown path
- the title
- the authors
- optional year and edition

That is the wrong UX for the target workflow. The new primary flow should be:

1. upload folder or ZIP
2. recursively detect textbook units
3. preview the detected textbooks
4. skip any unwanted units
5. submit the remaining units for background import

Manual metadata entry should not be required in this flow. The system should infer a usable title and identity automatically.

### 3. Textbook unit detection uses a recursive one-Markdown-subtree rule

The user requirement is:

- one textbook unit normally lives in one textbook subfolder
- that subfolder contains one main Markdown file
- images and resource files belong to that textbook
- the uploaded root may contain many such textbook subfolders nested multiple levels deep

To make that reliable, recursive detection should use a subtree-count rule rather than only scanning direct children.

For each directory under the upload root:

- compute how many Markdown files exist in its full subtree
- a directory is a textbook unit root when its subtree contains exactly one Markdown file and its parent subtree does not also qualify as the same single-textbook unit boundary
- the only Markdown file in that subtree is the textbook main file
- every file in that subtree belongs to that textbook unit

Practical effect:

- nested image folders remain attached to the textbook
- a large root folder containing many textbook subfolders gets split into multiple textbook units
- a root folder with only one textbook in it can still be treated as a single textbook import

Directories with zero Markdown files are ignored. Directories whose subtree contains multiple Markdown files are not textbook units in v1 and should continue descending until smaller valid units are found.

### 4. Textbook identity must not depend on hand-entered authors

The current `textbook_id` helper in `backend/app/ingest/textbook_pipeline.py` depends on `title + authors`. That is no longer sufficient once the new upload flow removes required author input.

The new design should introduce a shared textbook identity helper that derives a stable import identity from:

- normalized inferred title
- normalized main-Markdown content fingerprint

This helper must be shared by:

- textbook upload scanning
- textbook upload commit
- single-textbook ingestion

This keeps scan-time conflict detection and commit-time ingestion consistent.

### 5. Textbook upload gets its own session model and task type

Textbook upload should not reuse the paper upload session state directly. The workflows share transport mechanics, but the scan model is materially different.

Textbook upload should have:

- its own upload session storage
- its own scan cache
- its own skip action
- its own commit action
- its own batch task type

This avoids paper-specific fields like DOI strategy and paper type leaking into textbook import logic.

### 6. The paper detail graph is a structured preview, not a full exhaustive graph dump

The current paper detail graph tries to render all relevant logic, claims, and citations directly. That is what makes it crowded and hard to read.

The redesigned graph should be treated as a navigation-oriented preview. It should preserve the important structure, but it does not need to render every citation or every dense claim cluster as an individual always-visible node.

The graph preview should:

- always show the paper root
- always show logic-step nodes
- show claims in clustered groups with adaptive wrapping
- show citations in a dedicated citation cluster with a preview cap
- use summary/overflow nodes when a cluster would otherwise become unreadable

Example:

- citation cluster shows the top `N` citation nodes by mention count
- remaining citations collapse into a `更多引文 +N` summary node
- very dense claim clusters can similarly use a `更多论断 +N` summary node

Clicking an overflow node should open the relevant tab and explain that the full list lives there.

### 7. The new visual direction uses B-style clustered islands with A-style layout constraints

The approved visual direction is `B`, but the user also explicitly wants node overlap reduced.

That means the implementation should not use a fully free-form force layout. Instead it should use:

- clustered visual styling inspired by the `B` direction
- constrained position bands so the graph remains legible

Recommended zone model:

- paper root near the upper center
- logic-step cluster in a middle arc or band
- claim clusters below their parent logic groups
- citation cluster in a right-side island or dock

This preserves the exploratory clustered look while keeping types from collapsing into one dense mass.

## Frontend Design

## `/ingest` Page

### Page structure

`frontend/src/pages/IngestPage.tsx` should keep one overall page, but it should render three major sections in order:

1. `论文导入`
2. `教材导入`
3. `已导入源管理`

The paper section keeps the existing flow. The textbook section is new and independent.

### Textbook import block

The textbook block should mirror the usability of paper upload without reusing paper-specific wording.

It should include:

- textbook ZIP upload
- textbook folder upload
- upload progress
- textbook upload session restore by `upload_id`
- scan summary cards
- a scan result list
- a commit button for ready textbook units

The scan summary should report textbook-specific counts such as:

- current session
- detected textbooks
- ready to import
- conflicts or errors
- active task state

### Textbook scan result list

Each detected textbook row should show:

- inferred title
- relative unit root
- main Markdown relative path
- asset/resource file count
- detected status

Statuses should include:

- `ready`
- `conflict`
- `error`
- `skipped`

Per-row actions in v1:

- `跳过`

There is no replace/merge action in v1.

### Textbook copy and behavior

The textbook block should not mention DOI, paper type, or paper conflict language.

The copy should stay Chinese-first and only keep technical English where required, such as:

- ZIP
- Markdown
- upload_id
- FAISS

## Paper Detail Graph Workbench

### Layout

The paper detail graph panel in `frontend/src/pages/PaperDetailPage.tsx` should become a real workbench.

Desktop layout:

- left: graph canvas
- right: fixed node detail card

Narrow-screen fallback:

- graph canvas first
- detail card below the graph

The one-line meta strip under the graph is not sufficient as the primary detail surface anymore.

### Node detail card

The right-side detail card should show stable information for the selected node:

- node title
- node type label
- short detail text
- related action button, when applicable
- selection hint if nothing is selected

Expected action examples:

- `打开逻辑步骤`
- `打开论断`
- `打开引用`
- `查看完整列表`

### Graph copy normalization

The touched paper detail surface should convert obvious English labels to Chinese, for example:

- `Current node id`
- `Coverage`
- `Review`
- `No pending review`

Technical terms such as `DOI`, `FAISS`, `Crossref`, and `Neo4j` may remain.

## Visual Design

## Paper graph node styling

The current graph uses too many visually similar rounded rectangles. The redesign should make node roles clearer at a glance.

Recommended style language:

- paper root: large luminous capsule or island card
- logic nodes: medium floating cards with a distinct cyan family
- claim nodes: compact labeled pills with a softer violet family
- citation nodes: slim amber chips in a dedicated citation island
- summary nodes: neutral grouped cards such as `更多引文 +N`

Edges should be softer and less dominant than the current flat preview. Selected-neighborhood emphasis should come from:

- brighter node border/fill
- clearer local edge emphasis
- gentler fade on unrelated nodes

### Overlap control

Node overlap should be addressed in two ways together:

1. better layout constraints
2. fewer simultaneously rendered nodes in dense clusters

It should not rely only on visual scaling.

Recommended rules:

- logic nodes get evenly spaced anchor positions
- claims wrap in a small per-logic grid under their parent
- citations render in a bounded side cluster
- dense overflow collapses into summary nodes instead of forcing every node onto the canvas

This is the key requirement that turns the redesign from “prettier” into “actually more usable.”

## Backend Design

## Textbook upload units

Introduce textbook-upload-specific units under `backend/app/ingest/` rather than overloading paper upload modules.

Suggested responsibilities:

- `textbook_upload_store.py`
  stores textbook upload sessions, staged files, and scan cache
- `scan_textbook_upload.py`
  recursively detects textbook units and computes scan results
- `textbook_upload_actions.py`
  implements skip and commit behaviors for textbook upload sessions

These modules should stay textbook-specific even if they share a few low-level helpers with paper upload later.

## Router contracts

Textbook upload should expose a parallel upload API family.

Suggested endpoints:

- `POST /textbooks/upload/start`
- `POST /textbooks/upload/chunk`
- `GET /textbooks/upload/status`
- `POST /textbooks/upload/finish`
- `GET /textbooks/upload/scan`
- `POST /textbooks/upload/skip`
- `POST /textbooks/upload/commit_ready`

Behavior should mirror paper upload at the transport level:

- chunked upload support
- resumable upload by `upload_id`
- scan result returned after finish

But the scan payload and commit semantics are textbook-specific.

## Shared identity helper

Add one shared helper for textbook identity inference so scan-time predictions and commit-time ingestion stay aligned.

Suggested outputs:

- inferred title
- normalized title
- content fingerprint
- derived `textbook_id`

The existing single-textbook ingestion flow should call this helper too, even if it still allows optional metadata overrides later.

## Textbook scan model

Each textbook scan unit should include at least:

- `unit_id`
- `unit_rel_dir`
- `main_md_rel_path`
- `title`
- `textbook_id`
- `asset_count`
- `status`
- `error`

Optional but useful:

- `content_fingerprint`
- `existing_textbook_id`

### Conflict handling

If a detected textbook unit resolves to a `textbook_id` that already exists, the unit should be marked `conflict` during scan.

In v1:

- conflict units are visible
- conflict units are not committed by `commit_ready`
- the user may skip them

There is no replace/merge flow yet.

## Textbook commit task

Add a textbook-upload batch task type rather than submitting one foreground request per textbook.

Suggested task type:

- `ingest_textbook_upload_ready`

Commit behavior:

1. load the upload session
2. iterate through `ready` units that are not skipped
3. ingest one textbook at a time through the existing textbook pipeline
4. record per-unit results
5. keep going on single-unit failure
6. return a structured batch summary

The task result should make partial success explicit.

## Paper graph preview model

The paper graph builder in `frontend/src/pages/PaperDetailPage.tsx` already creates a derived graph model. That pattern should remain, but the preview model should gain explicit cluster summarization rules.

Suggested preview rules:

- root: always present
- logic steps: all present
- claims: grouped by step type, adaptive per-step cap with overflow node
- citations: sorted by mention count, capped preview plus overflow node

This keeps the detail tabs as the source of full exhaustive content while making the graph preview actually readable.

## Error Handling

## Textbook upload

Textbook upload must treat unit-level failure as local, not global.

Required cases:

- invalid ZIP or unsafe extraction
- upload session missing or expired
- no valid textbook units detected
- ambiguous multi-Markdown subtree
- predicted textbook conflict
- textbook ingestion failure for one unit

The scan response should surface these clearly so the user can still import unaffected textbooks.

## Paper detail graph

The graph workbench should degrade gracefully when:

- no graph detail exists yet
- the selected node meta is missing
- an overflow node is selected
- the action target tab is unavailable

In those cases, the detail card should still render a readable fallback instead of looking empty or broken.

## Testing

## Backend tests

Add focused tests for:

- recursive textbook unit detection
- highest-valid single-Markdown subtree selection
- title inference fallback order
- textbook identity generation from inferred title plus content
- scan conflict marking
- textbook skip action
- textbook batch commit partial success behavior

## Frontend tests

Add focused tests for:

- `/ingest` rendering separate paper and textbook blocks
- textbook upload summary and scan result rendering
- textbook skip interaction
- textbook commit action wiring
- paper detail graph detail-card rendering after selection
- paper detail graph empty-state detail card
- overflow-node detail behavior
- Chinese copy on the touched paper detail surface

## Verification expectations

Before implementation is considered complete, verification should cover:

- textbook upload tests
- paper detail graph tests
- existing ingest-page tests
- frontend lint
- any touched backend API tests

## Open Questions Resolved During Brainstorming

The following decisions are now fixed and should not be reopened during implementation planning unless a hard technical blocker appears:

- textbook import stays on the same `/ingest` page as paper import
- paper import and textbook import are separate work areas, not tabs and not separate routes
- textbook import should use folder/ZIP upload, not a large manual metadata form
- recursive scanning must support large nested directories that contain multiple textbook subfolders
- each textbook unit in v1 assumes one main Markdown file
- the paper detail graph should use a right-side fixed detail card
- the paper detail graph visual direction should follow the `B` clustered-island look, but with enough layout constraints to prevent overlap

