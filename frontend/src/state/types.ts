// frontend/src/state/types.ts

export type ModuleId =
  | 'overview'
  | 'papers'
  | 'ask'
  | 'evolution'
  | 'textbooks'
  | 'ops'

// ── Graph data ──────────────────────────────────────────────
export type GraphNodeData = {
  id: string
  label: string
  shortLabel?: string
  description?: string
  kind: string        // 'paper' | 'logic' | 'claim' | 'prop' | 'group' | 'entity' | 'citation'
  // Type-specific optional fields
  qualityTier?: string   // 'A1' | 'A2' | 'B1' | 'B2' | 'C'
  ingested?: boolean
  inScope?: boolean
  year?: number
  confidence?: number    // 0–1, drives opacity for claims
  state?: string         // proposition state: 'stable' | 'challenged' | 'superseded'
  paperId?: string
  textbookId?: string
  chapterId?: string
  communityId?: string
  clusterKey?: string
  propId?: string
  // Display
  degree?: number
  mentions?: number
}

export type GraphEdgeData = {
  id: string
  source: string
  target: string
  kind: string        // 'cites' | 'supports' | 'challenges' | 'supersedes' | 'similar' | 'maps_to' | 'relates_to' | 'contains' | 'evidenced_by'
  weight?: number
  totalMentions?: number
  purposeLabels?: string[]
}

export type GraphElement =
  | { group: 'nodes'; data: GraphNodeData }
  | { group: 'edges'; data: GraphEdgeData }

export type LayoutName =
  | 'cose'      // force-directed (overview, papers)
  | 'dagre'     // hierarchical (ask)
  | 'breadthfirst'  // tree (textbooks)
  | 'concentric'    // focal (paper neighborhood)
  | 'preset'    // keep current positions

export type GraphUpdateReason = 'replace' | 'merge' | 'relayout'

// ── Selected node context ────────────────────────────────────
export type SelectedNode = {
  id: string
  kind: string
  label: string
  description?: string
  paperId?: string
  textbookId?: string
  chapterId?: string
  propId?: string
  route?: string
}

// ── Module-specific states ───────────────────────────────────
export type PapersModuleState = {
  selectedPaperId: string | null
  searchQuery: string
}

export type AskItem = {
  id: string
  question: string
  k: number
  createdAt: number
  status: 'running' | 'done' | 'error'
  answer?: string
  evidence?: Array<{
    paper_id?: string
    paper_source?: string
    paper_title?: string
    md_path?: string
    start_line?: number
    end_line?: number
    score?: number
    snippet?: string
  }>
  fusionEvidence?: Array<{
    paper_source?: string
    paper_id?: string
    logic_step_id?: string
    step_type?: string
    entity_id?: string
    entity_name?: string
    entity_type?: string
    description?: string
    score?: number
    rank_score?: number
    reasons?: string[]
    evidence_chunk_ids?: string[]
    source_chunk_id?: string
    evidence_quote?: string
    source_chapter_id?: string
    textbook_id?: string
    textbook_title?: string
    chapter_id?: string
    chapter_num?: number
    chapter_title?: string
  }>
  dualEvidenceCoverage?: boolean
  graphContext?: Array<{
    paper_source?: string
    cited_doi?: string
    cited_title?: string
    total_mentions?: number
    purpose_labels?: string[]
  }>
  structuredKnowledge?: {
    logic_steps?: Array<{
      paper_source?: string
      step_type?: string
      summary?: string
    }>
    claims?: Array<{
      claim_id?: string
      paper_source?: string
      step_type?: string
      text?: string
      confidence?: number
    }>
  } | null
  retrievalMode?: string
  notice?: string
  insufficientScopeEvidence?: boolean
  error?: string
}

export type AskModuleState = {
  history: AskItem[]
  currentId: string | null
  draftQuestion: string
  draftK: number
}

export type EvolutionModuleState = {
  selectedGroupId: string | null
  searchQuery: string
}

export type TextbooksModuleState = {
  selectedTextbookId: string | null
  selectedChapterId: string | null
}

// ── Global state ─────────────────────────────────────────────
export type GlobalState = {
  activeModule: ModuleId
  graphElements: GraphElement[]
  graphLayout: LayoutName
  layoutTrigger: number       // increment to force layout re-run
  graphUpdateReason: GraphUpdateReason
  selectedNode: SelectedNode | null
  transitioning: boolean

  // Module states
  papers: PapersModuleState
  ask: AskModuleState
  evolution: EvolutionModuleState
  textbooks: TextbooksModuleState
}

// ── Actions ──────────────────────────────────────────────────
export type GlobalAction =
  | { type: 'SET_MODULE'; module: ModuleId }
  | { type: 'SET_GRAPH'; elements: GraphElement[]; layout: LayoutName }
  | { type: 'MERGE_GRAPH'; elements: GraphElement[] }  // Add without clearing
  | { type: 'SET_SELECTED'; node: SelectedNode | null }
  | { type: 'SET_TRANSITIONING'; value: boolean }
  | { type: 'RELAYOUT' }
  // Paper module
  | { type: 'PAPERS_SELECT'; paperId: string | null }
  | { type: 'PAPERS_SEARCH'; query: string }
  // Ask module
  | { type: 'ASK_SET_DRAFT'; question?: string; k?: number }
  | { type: 'ASK_ADD_ITEM'; item: AskItem }
  | { type: 'ASK_UPDATE_ITEM'; id: string; patch: Partial<AskItem> }
  | { type: 'ASK_SET_CURRENT'; id: string | null }
  | { type: 'ASK_RESET_SESSION'; keepDraft?: boolean }
  | { type: 'ASK_RESTORE'; ask: AskModuleState }
  // Evolution module
  | { type: 'EVOLUTION_SELECT_GROUP'; groupId: string | null }
  | { type: 'EVOLUTION_SEARCH'; query: string }
  // Textbooks module
  | { type: 'TEXTBOOKS_SELECT'; textbookId: string | null; chapterId: string | null }
