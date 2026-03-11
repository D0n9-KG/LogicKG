# Global Community Migration Design

## Goal

Replace the current proposition/evolution-centric organization with a community-centric architecture that is more useful for whole-graph clustering across textbook and paper knowledge. The new core should:

- keep Tencent Youtu-GraphRAG responsible for chapter-level extraction only
- move all meaningful community detection to LogicKG local infrastructure
- remove `Proposition`, `PropositionGroup`, and the `evolution` module
- make `GlobalCommunity` the shared structural layer consumed by Ask, discovery, overview, and textbook workflows

## Key Decisions

### 1. Youtu only extracts, does not cluster

The remote `youtu-graphrag` service currently runs TreeComm during graph construction. That is not suitable for LogicKG because textbook content is sent chapter by chapter and because the desired clustering scope includes non-Youtu paper graph content. The remote pipeline should therefore stop after entity/relation extraction and deduplication, and must not emit chapter-local community results for LogicKG consumption.

This requires a small upstream patch in Youtu so `process_level4()` becomes optional, for example via `enable_tree_comm: false`.

### 2. LogicKG owns global community detection

LogicKG should build one unified in-memory graph from local Neo4j data and run a local adaptation of Youtu `FastTreeComm` on that full graph. The first version should stay as close as possible to Youtu behavior:

- use a `networkx.MultiDiGraph`
- ensure nodes expose `properties.name`
- ensure edges expose `relation`
- rely on TreeComm structural plus semantic similarity
- do not add custom cross-source bridge edges in v1

### 3. Proposition and evolution are removed

The current proposition layer only merges items when normalized text hashes match. That is not strong enough to justify keeping a separate semantic bridge layer. Since the long-term target is community-first organization, both `Proposition` and proposition-based evolution should be removed instead of being retained as compatibility layers.

## Global Graph Projection

### Included nodes

Version one of the global clustering graph should include:

- `KnowledgeEntity`
- `Claim`
- `LogicStep`

These are the currently available node types with real knowledge semantics and stable textual representations. The first version should not include `Paper`, `Chunk`, `ReferenceEntry`, `Figure`, or `EvidenceEvent`, because they are container, evidence, or metadata nodes and would add noise to community detection.

### Included edges

The projection should keep real source-internal graph structure only:

- textbook `RELATES_TO`
- paper `HAS_CLAIM`
- optional paper-side similarity edges such as `SIMILAR_CLAIM` and `SIMILAR_LOGIC` when they are already available and stable

The first version should not synthesize new cross-source bridge edges. Cross-source cohesion should come from TreeComm semantic similarity operating over the unified node set.

## New Community Layer

Introduce a new graph layer instead of reusing fusion community storage:

- `GlobalCommunity`
- `GlobalKeyword`
- `IN_GLOBAL_COMMUNITY`
- `HAS_GLOBAL_KEYWORD`

Suggested `GlobalCommunity` fields:

- `community_id`
- `title`
- `summary`
- `confidence`
- `member_count`
- `version`
- `built_at`

Suggested `GlobalKeyword` fields:

- `keyword_id`
- `keyword`
- `rank`
- `weight`
- `community_id`

Membership edges should be allowed from `KnowledgeEntity`, `Claim`, and `LogicStep` to `GlobalCommunity`.

## Module Adaptation

### Ask

Ask should move from proposition retrieval to community retrieval.

New flow:

1. retrieve `GlobalCommunity` rows
2. rank communities by title, keyword, representative members, and coverage metadata
3. expand winning communities into member nodes
4. collect actual evidence from member-linked chunks, chapters, or claim evidence

The graph shown in Ask should become:

`community -> member -> evidence`

instead of:

`logic/claim -> proposition`

### Discovery

Discovery should replace `source_proposition_ids` with `source_community_ids`.

Gap mining should pivot from proposition-specific ideas to community-specific ideas, such as:

- high-conflict communities
- communities with weak evidence coverage
- communities heavily covered in textbooks but weakly validated in papers
- dense topic communities with sparse benchmark or evaluation support

Context expansion should resolve papers and chapters through community members rather than proposition mappings.

### Textbook workflow

Textbook ingestion should keep the existing split, remote extraction, import, and entity relation storage flow. After import completes, it should trigger local global community rebuild instead of proposition mapping.

The old textbook endpoint that creates proposition links should be removed or repurposed into a community rebuild endpoint.

## Deletions

The migration should remove:

- `backend/app/evolution/`
- `backend/app/tasks/clustering_task.py`
- proposition creation inside paper ingest
- textbook proposition mapping and related helper modules
- proposition-related config entries
- proposition/evolution APIs
- evolution task registration
- evolution panel, loaders, state, and tasks UI

Neo4j cleanup should delete:

- `Proposition`
- `PropositionGroup`
- proposition relation edges such as `MAPS_TO`, `IN_GROUP`, `SUPPORTS`, `CHALLENGES`, `SUPERSEDES`
- evolution-only `EvidenceEvent` usage if no longer consumed elsewhere

## Migration Order

1. Patch remote Youtu to allow extraction without TreeComm
2. Add local global community projection, TreeComm adapter, and persistence
3. Add community retrieval and community expansion APIs
4. Switch Ask to community-first retrieval
5. Switch discovery to community-based gaps and evidence auditing
6. Remove proposition/evolution ingest, clustering, APIs, tasks, and frontend entry points
7. Clean old graph data and old FAISS corpora

## Validation Targets

The migration is successful when:

- textbook import still produces usable entity/relation graphs
- remote Youtu no longer emits chapter communities used by LogicKG
- local rebuild generates stable `GlobalCommunity` results over textbook plus paper graph content
- Ask can answer using community-driven retrieval with real grounding
- discovery can generate useful community-based gaps
- no runtime path depends on proposition or evolution data
