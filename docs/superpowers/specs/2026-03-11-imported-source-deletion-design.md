# Imported Source Deletion Design

## Goal

Add a user-facing deletion workflow so users can remove already imported paper or textbook data from the frontend.

The first version should:

- support single-item quick deletion from the side panels
- support batch deletion from `/ingest`
- separate paper and textbook batch operations in `/ingest`
- show papers in grouped sections for `ingested` vs `metadata-only`
- prefer human-readable paper titles over raw IDs in management views
- allow partial success in batch deletion
- trigger one automatic post-delete rebuild per successful batch

## Existing Context

The current codebase already has part of the needed behavior:

- `frontend/src/panels/PapersPanel.tsx` already exposes single-paper deletion
- `backend/app/api/routers/paper_edits.py` already deletes ingested paper graph data and derived paper artifacts
- `backend/app/api/routers/textbooks.py` already exposes `DELETE /textbooks/{textbook_id}`
- `frontend/src/panels/TextbooksPanel.tsx` does not yet expose textbook deletion
- `frontend/src/pages/IngestPage.tsx` currently focuses on import and rebuild tasks, not lifecycle management of existing assets
- `backend/app/graph/neo4j_client.py:list_papers()` only returns `ingested = true` papers, so it cannot directly power the `/ingest` management view that must also show metadata-only paper stubs

This means v1 is not a greenfield delete feature. It is a unification and expansion effort: reuse the existing paper delete capability, surface textbook deletion in the UI, and add a dedicated management view plus task-based batch orchestration.

## Approved Scope

### In scope

- single paper delete from `PapersPanel`
- single textbook delete from `TextbooksPanel`
- a new management section inside `/ingest`
- batch delete for papers inside `/ingest`
- batch delete for textbooks inside `/ingest`
- one batch result summary that can report success and failure counts together
- automatic rebuild after a successful delete batch
- deletion of textbook database data plus textbook-derived local artifact files

### Out of scope

- mixed paper and textbook deletion in a single batch request
- multi-select deletion in side panels
- deletion of metadata-only paper stubs
- deletion of textbook source markdown files or source directories
- all-or-nothing transactional rollback across the whole batch
- reuse of `rebuild/all` as the delete follow-up mechanism

## Key Decisions

### 1. Keep two UX layers

Deletion should exist in two different frontend surfaces with different jobs:

- side panels are for fast, single-item deletion
- `/ingest` is for grouped lifecycle management and batch deletion

This keeps the side panels lightweight while still giving users a central place to clean up imported data in bulk.

### 2. Batch deletion is type-separated

`/ingest` should render two independent management blocks:

- paper management
- textbook management

Each block owns its own selection state, delete action, and result summary. A single request must never mix paper IDs and textbook IDs.

### 3. Papers are grouped by ingest state

The paper management view in `/ingest` must show:

- `Ingested Papers`
- `Metadata-only Papers`

Only the ingested group is deletable. Metadata-only papers remain visible for context, but cannot be selected or deleted in v1.

### 4. Titles are first-class display values

Management views must prefer readable titles over raw paper IDs.

The backend should provide a stable `display_title` field with fallback order:

1. `title`
2. `paper_source`
3. `paper_id`

This avoids duplicated fallback logic across multiple frontend surfaces and guarantees that both lists and task summaries stay readable.

### 5. Delete operations become task-oriented

The current system already has a task queue and task polling flow. The deletion feature should align with that instead of introducing new synchronous long-running UX.

All user-facing deletes should submit tasks:

- side-panel single delete submits a task with one ID
- `/ingest` batch delete submits a task with multiple IDs

This makes progress reporting, partial success reporting, and post-delete rebuild orchestration consistent.

### 6. Post-delete rebuild is precise, not generic

Delete follow-up should not call `rebuild/all`, because that flow is oriented around rebuilding every paper and then rebuilding FAISS.

Instead, successful delete batches should trigger one follow-up rebuild sequence inside the delete task:

1. rebuild global communities
2. rebuild global FAISS

This is the minimal rebuild needed to restore consistency for graph views, retrieval, and Ask behavior after asset removal.

## Frontend Design

## Side Panels

### Papers panel

Keep the current delete affordance in `frontend/src/panels/PapersPanel.tsx`, but change the action model from “fire synchronous delete and refresh immediately” to “submit delete task, poll task, then refresh”.

Behavior:

- one delete button per row
- existing confirmation modal remains
- confirmation text should explicitly mention graph data, derived files, and automatic rebuild
- after task completion, invalidate paper and overview caches and refresh the list
- if the deleted paper was selected, clear `selectedPaperId`

### Textbooks panel

Add symmetric single-item deletion to `frontend/src/panels/TextbooksPanel.tsx`.

Behavior:

- one delete button per textbook row in the textbook list
- side panel stays single-delete only
- confirmation text should explicitly mention graph data, textbook-derived artifact files, and automatic rebuild
- after task completion, invalidate textbook and overview caches and refresh the list
- if the deleted textbook or one of its chapters was selected, clear `selectedTextbookId` and `selectedChapterId`

## `/ingest` Management Section

Add a new “Imported Source Management” section below the existing import workflows in `frontend/src/pages/IngestPage.tsx`.

### Paper management block

The paper block should include:

- search input
- grouped sections for ingested vs metadata-only
- checkboxes only for ingested papers
- a batch action bar showing selected count
- a destructive action button to submit batch deletion
- task result summary and per-item outcome details

The metadata-only group should:

- remain visible
- show readable titles
- show that deletion is unavailable in v1
- not participate in checkbox selection

### Textbook management block

The textbook block should include:

- list of textbooks
- multi-select checkboxes
- batch action bar showing selected count
- destructive action button to submit batch deletion
- task result summary and per-item outcome details

### Shared frontend behavior

Both blocks should:

- disable destructive actions while the current delete task is active
- surface partial-success summaries such as “deleted N, failed M”
- refresh data after task completion
- clear stale selection after refresh if some selected items no longer exist

## Backend Design

## Reusable delete services

The actual delete behavior should move behind reusable service functions instead of remaining embedded only in routers.

Suggested units:

- `delete_paper_asset(paper_id: str, hard_delete: bool = True) -> dict`
- `delete_textbook_asset(textbook_id: str) -> dict`

Responsibilities:

- validate existence and deletability
- delete graph data
- delete owned derived artifacts
- return structured result details for task aggregation

Routers and task handlers should both call these services.

## Management list API for papers

Add a dedicated paper-management endpoint for `/ingest`.

Suggested contract:

`GET /papers/manage`

Suggested response fields per paper:

- `paper_id`
- `display_title`
- `title`
- `paper_source`
- `doi`
- `year`
- `ingested`
- `deletable`
- `collections`

Behavior:

- return both ingested and metadata-only paper nodes
- mark only ingested papers as deletable in v1
- support basic query filtering by title, source, DOI, or paper ID
- keep response ordering stable and management-friendly

This endpoint should not replace `/graph/papers`. It exists because the management page has different data requirements than the graph-oriented paper list.

## Delete task submission APIs

Add two task-submission endpoints:

- `POST /tasks/delete/papers`
- `POST /tasks/delete/textbooks`

Suggested payloads:

- `{ "paper_ids": ["..."], "trigger_rebuild": true }`
- `{ "textbook_ids": ["..."], "trigger_rebuild": true }`

`trigger_rebuild` should default to `true`. It is fixed by product scope in v1, but keeping the field now avoids painting the contract into a corner.

## Task types and handlers

Add new task types:

- `delete_papers_batch`
- `delete_textbooks_batch`

Each handler should:

1. validate and de-duplicate input IDs
2. iterate through items without aborting on single-item failures
3. collect per-item result records
4. trigger one rebuild sequence if at least one delete succeeded
5. return a structured batch summary

Suggested result payload:

- `requested_count`
- `deleted_count`
- `failed_count`
- `skipped_count`
- `results`
- `rebuild`

Each `results[]` item should include:

- target ID
- target type
- status: `deleted | failed | skipped`
- message or error
- file cleanup details where applicable

## Textbook artifact deletion

Textbook deletion must remove:

- textbook graph data in Neo4j
- textbook chapters
- textbook-owned knowledge entities
- persisted textbook-derived artifacts under `backend/storage/textbooks/<safe-textbook-name>/`

For v1, a `KnowledgeEntity` is considered textbook-owned when all inbound `HAS_ENTITY` relationships come from chapters that belong to the textbook being deleted.

This means:

- if an entity is attached only to chapters of the target textbook, it is deleted
- if an entity is also attached to a chapter of another textbook, it is preserved
- incidental relationships such as `EXPLAINS`, community membership edges, or other non-`HAS_ENTITY` links do not make the entity shared; they are removed by detach-delete only when the entity itself qualifies as textbook-owned

Textbook deletion must not remove:

- original source markdown files
- the source directory referenced by `Textbook.source_dir`

This aligns with the approved scope: delete imported results and derived artifacts, not user-authored source material.

## Error Handling and Edge Cases

### Partial success is a first-class outcome

The task system currently supports `queued`, `running`, `succeeded`, `failed`, and `canceled`, but has no `partial_success` state.

For delete batches, the task should be marked `succeeded` when the batch run itself completed, even if some individual items failed. The detailed per-item counts and result rows communicate the mixed outcome.

The task should only be marked `failed` when the batch itself could not run meaningfully, for example:

- invalid payload shape
- empty ID list after normalization
- unexpected infrastructure failure before iteration begins

### Per-item outcome rules

The task result must use deterministic per-item rules so planning and frontend messaging stay stable.

Suggested v1 outcome matrix:

- duplicate ID in the same request after the first occurrence: `skipped`
- metadata-only paper submitted to the paper delete API: `skipped`
- item exists but is outside v1 deletable scope: `skipped`
- requested ID does not exist: `failed`
- delete attempt throws an execution error: `failed`
- delete completes successfully: `deleted`

This gives `skipped` a clear meaning: the item was intentionally not acted on due to normalization or business rules. `failed` means the request targeted something that should have been actionable but could not be completed safely.

### Rebuild trigger conditions

- if `deleted_count > 0`, run one rebuild sequence
- if `deleted_count == 0`, do not rebuild

This prevents unnecessary rebuild work when the whole batch was rejected or failed item-by-item.

### Rebuild failure semantics

Automatic rebuild is part of the delete contract in v1, so rebuild failure cannot be treated as a silent warning.

If at least one item was deleted but the follow-up rebuild fails:

- the task should be marked `failed`
- the task `result` must still include the completed delete summary and per-item outcomes
- the `rebuild` block must explicitly report `status = failed` plus the stage or error
- the frontend should show that deletion completed but post-delete rebuild did not, so the user understands the graph and retrieval state may be temporarily inconsistent

If no items were deleted, rebuild is skipped and cannot fail.

### File cleanup should be best-effort after graph deletion

Graph deletion is the primary action. Derived file cleanup should not force a batch rollback if the graph deletion has already succeeded.

Instead:

- graph deletion success should still count as deleted
- cleanup failures should be captured in per-item result details
- the final task summary should surface those warnings

### UI stale-state cleanup

After a successful delete task finishes, the frontend should clear stale state if it references removed objects:

- selected paper
- selected textbook
- selected chapter
- selected batch checkboxes
- cached overview graph elements and stats

This avoids rendering “ghost” selections for objects that no longer exist.

## Testing Strategy

## Backend tests

Add targeted tests for:

- paper management list endpoint returning both ingested and metadata-only papers with `display_title` and `deletable`
- paper batch delete handler with full success
- paper batch delete handler with partial success
- textbook batch delete handler with full success
- textbook batch delete handler with partial success
- rebuild running exactly once after a partially successful batch
- rebuild not running when nothing was deleted
- textbook derived artifact cleanup without deleting source markdown or source directories

## Frontend tests

Add targeted tests for:

- `TextbooksPanel` single-delete affordance and task-based refresh
- `/ingest` paper management grouping and metadata-only non-deletable behavior
- `/ingest` batch delete selection for papers
- `/ingest` batch delete selection for textbooks
- task result summary rendering for partial success
- cache invalidation and selected-state clearing after deletion completes

## Validation Targets

The design is successful when:

- users can delete one paper from the papers side panel
- users can delete one textbook from the textbooks side panel
- users can batch delete papers from `/ingest`
- users can batch delete textbooks from `/ingest`
- `/ingest` shows papers grouped by ingested vs metadata-only
- metadata-only papers are visible but not deletable
- management views show paper titles rather than raw IDs whenever possible
- batch tasks can report mixed outcomes without pretending the whole batch failed
- each successful delete batch triggers one and only one follow-up rebuild sequence
- overview, panel lists, and retrieval state are refreshed into a consistent post-delete state
