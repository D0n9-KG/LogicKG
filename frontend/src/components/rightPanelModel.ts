import type { GraphEdgeData, GraphNodeData, SelectedNode } from '../state/types'

export type RelationRow = {
  kind: string
  label: string
  count: number
}

export type NodeContentState = {
  full: string
  preview: string
  truncated: boolean
}

export type EvidenceRow = {
  paper_id?: string
  paper_source?: string
  paper_title?: string
  md_path?: string
  start_line?: number
  end_line?: number
  score?: number
  snippet?: string
}

export type FusionEvidenceRow = {
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
}

export type FusionChapterSummary = {
  chapterId: string
  label: string
  textbookTitle: string
  entityCount: number
  count: number
  avgScore: number | null
}

export type FusionEvidenceStats = {
  total: number
  scored: number
  avgScore: number | null
  textbookCount: number
  chapterCount: number
  entityCount: number
  paperSourceCount: number
  topChapters: FusionChapterSummary[]
}

export type NeighborRow = {
  id: string
  label: string
  kind: string
  links: number
  inCount: number
  outCount: number
  relations: string[]
}

export type TimelineRow = {
  key: string
  year: number | null
  total: number
  supports: number
  challenges: number
  cites: number
  evidencedBy: number
  samples: string[]
}

export type GenericNodeContext = {
  center: GraphNodeData | null
  relationRows: Array<{ kind: string; count: number }>
  neighbors: NeighborRow[]
  childNeighbors: NeighborRow[]
  parentNeighbors: NeighborRow[]
  timeline: TimelineRow[]
  timelinePeak: number
  timelineRange: string
  degree: number
  relationDiversity: number
  neighborCount: number
  inCount: number
  outCount: number
  qualityScore: number | null
  raw: {
    selectedNode: SelectedNode
    center: GraphNodeData | null
  }
}

type BuildNodeContentArgs = {
  label?: unknown
  description?: unknown
  maxChars?: number
}

function normalizeText(value: unknown): string {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
}

function sortByScoreThenLabel<T extends { score?: unknown; rank_score?: unknown }>(rows: T[], labelOf: (row: T) => string): T[] {
  return [...rows].sort((a, b) => {
    const rankA = Number(a.rank_score)
    const rankB = Number(b.rank_score)
    const safeRankA = Number.isFinite(rankA) ? rankA : -Infinity
    const safeRankB = Number.isFinite(rankB) ? rankB : -Infinity
    if (safeRankA !== safeRankB) return safeRankB - safeRankA

    const scoreA = Number(a.score)
    const scoreB = Number(b.score)
    const safeScoreA = Number.isFinite(scoreA) ? scoreA : -Infinity
    const safeScoreB = Number.isFinite(scoreB) ? scoreB : -Infinity
    if (safeScoreA !== safeScoreB) return safeScoreB - safeScoreA

    return labelOf(a).localeCompare(labelOf(b))
  })
}

function toPositiveNumber(value: unknown): number | null {
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return n
}

function chapterLabel(row: FusionEvidenceRow): string {
  const title = normalizeText(row.chapter_title)
  const chapterId = normalizeText(row.chapter_id || row.source_chapter_id)
  const chapterNum = Number(row.chapter_num)
  if (Number.isFinite(chapterNum)) {
    return title ? `Ch.${Math.round(chapterNum)} ${title}` : `Ch.${Math.round(chapterNum)}`
  }
  return title || chapterId || 'chapter'
}

function safeMaxChars(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return 220
  return Math.max(60, Math.min(800, Math.round(n)))
}

function validYear(value: unknown): number | null {
  const year = Number(value ?? 0)
  if (!Number.isFinite(year)) return null
  if (year < 1900 || year > 2100) return null
  return Math.round(year)
}

function compareNeighborRows(a: NeighborRow, b: NeighborRow): number {
  return b.links - a.links || b.outCount - a.outCount || b.inCount - a.inCount || a.label.localeCompare(b.label)
}

function nodeDisplayLabel(node: GraphNodeData | undefined, fallbackId: string): string {
  if (!node) return fallbackId
  if (node.kind === 'paper') {
    return normalizeText(node.description) || normalizeText(node.label) || fallbackId
  }
  return normalizeText(node.label) || fallbackId
}

export function buildNodeContentState(args: BuildNodeContentArgs): NodeContentState {
  const full = normalizeText(args.description) || normalizeText(args.label)
  const maxChars = safeMaxChars(args.maxChars)
  if (full.length <= maxChars) {
    return {
      full,
      preview: full,
      truncated: false,
    }
  }
  return {
    full,
    preview: `${full.slice(0, maxChars).trimEnd()}...`,
    truncated: true,
  }
}

export function rankRelationRows(rows: RelationRow[], limit = 8): RelationRow[] {
  const cap = Math.max(1, Math.min(30, Math.round(limit)))
  return [...rows]
    .filter((row) => Number.isFinite(row.count) && row.count > 0)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, cap)
}

export function filterEvidenceRows(rows: EvidenceRow[], query: string, limit = 16): EvidenceRow[] {
  const cap = Math.max(1, Math.min(200, Math.round(limit)))
  const normalizedQuery = normalizeText(query).toLowerCase()
  const filtered = normalizedQuery
    ? rows.filter((row) =>
        [row.paper_title, row.paper_id, row.paper_source, row.md_path, row.snippet]
          .map((field) => normalizeText(field).toLowerCase())
          .some((field) => field.includes(normalizedQuery)),
      )
    : rows

  return [...filtered]
    .sort((a, b) => {
      const scoreA = Number(a.score)
      const scoreB = Number(b.score)
      const safeA = Number.isFinite(scoreA) ? scoreA : -Infinity
      const safeB = Number.isFinite(scoreB) ? scoreB : -Infinity
      if (safeA !== safeB) return safeB - safeA

      const keyA =
        normalizeText(a.paper_title) || normalizeText(a.paper_source) || normalizeText(a.paper_id) || normalizeText(a.md_path)
      const keyB =
        normalizeText(b.paper_title) || normalizeText(b.paper_source) || normalizeText(b.paper_id) || normalizeText(b.md_path)
      return keyA.localeCompare(keyB)
    })
    .slice(0, cap)
}

export function filterFusionEvidenceRows(rows: FusionEvidenceRow[], query: string, limit = 16): FusionEvidenceRow[] {
  const cap = Math.max(1, Math.min(200, Math.round(limit)))
  const normalizedQuery = normalizeText(query).toLowerCase()
  const filtered = normalizedQuery
    ? rows.filter((row) =>
        [
          row.paper_source,
          row.paper_id,
          row.step_type,
          row.entity_name,
          row.entity_type,
          row.description,
          row.evidence_quote,
          row.textbook_title,
          row.chapter_title,
          row.chapter_id,
          row.source_chapter_id,
        ]
          .map((field) => normalizeText(field).toLowerCase())
          .some((field) => field.includes(normalizedQuery)),
      )
    : rows

  return sortByScoreThenLabel(filtered, (row) =>
    normalizeText(row.entity_name) || normalizeText(row.chapter_title) || normalizeText(row.textbook_title) || 'fusion',
  ).slice(0, cap)
}

export function buildFusionEvidenceStats(rows: FusionEvidenceRow[]): FusionEvidenceStats {
  const textbookIds = new Set<string>()
  const chapterIds = new Set<string>()
  const entityIds = new Set<string>()
  const paperSources = new Set<string>()
  const scoredValues: number[] = []
  const chapterMap = new Map<
    string,
    {
      chapterId: string
      label: string
      textbookTitle: string
      entityIds: Set<string>
      count: number
      scores: number[]
    }
  >()

  for (const row of rows) {
    const textbookId = normalizeText(row.textbook_id)
    const chapterId = normalizeText(row.chapter_id || row.source_chapter_id)
    const entityId = normalizeText(row.entity_id)
    const paperSource = normalizeText(row.paper_source || row.paper_id)
    const textbookTitle = normalizeText(row.textbook_title)

    if (textbookId) textbookIds.add(textbookId)
    if (chapterId) chapterIds.add(chapterId)
    if (entityId) entityIds.add(entityId)
    if (paperSource) paperSources.add(paperSource)

    const score = toPositiveNumber(row.score)
    if (score !== null) scoredValues.push(score)

    if (!chapterId) continue
    const chapterRow =
      chapterMap.get(chapterId) ??
      ({
        chapterId,
        label: chapterLabel(row),
        textbookTitle,
        entityIds: new Set<string>(),
        count: 0,
        scores: [],
      } satisfies {
        chapterId: string
        label: string
        textbookTitle: string
        entityIds: Set<string>
        count: number
        scores: number[]
      })
    chapterRow.count += 1
    if (entityId) chapterRow.entityIds.add(entityId)
    if (score !== null) chapterRow.scores.push(score)
    if (!chapterRow.textbookTitle && textbookTitle) chapterRow.textbookTitle = textbookTitle
    chapterMap.set(chapterId, chapterRow)
  }

  const topChapters = Array.from(chapterMap.values())
    .map((row) => ({
      chapterId: row.chapterId,
      label: row.label,
      textbookTitle: row.textbookTitle,
      entityCount: row.entityIds.size,
      count: row.count,
      avgScore: row.scores.length ? row.scores.reduce((sum, value) => sum + value, 0) / row.scores.length : null,
    }))
    .sort((a, b) => b.count - a.count || (b.avgScore ?? -1) - (a.avgScore ?? -1) || a.label.localeCompare(b.label))
    .slice(0, 8)

  return {
    total: rows.length,
    scored: scoredValues.length,
    avgScore: scoredValues.length ? scoredValues.reduce((sum, value) => sum + value, 0) / scoredValues.length : null,
    textbookCount: textbookIds.size,
    chapterCount: chapterIds.size,
    entityCount: entityIds.size,
    paperSourceCount: paperSources.size,
    topChapters,
  }
}

export function buildGenericNodeContext(args: {
  selectedNode: SelectedNode | null
  nodes: GraphNodeData[]
  edges: GraphEdgeData[]
}): GenericNodeContext | null {
  const selectedNode = args.selectedNode
  if (!selectedNode) return null

  const nodeMap = new Map(args.nodes.map((node) => [node.id, node]))
  const center = nodeMap.get(selectedNode.id) ?? null
  const relationCounts = new Map<string, number>()
  const neighborMap = new Map<string, NeighborRow>()
  const timelineMap = new Map<string, TimelineRow>()

  let inCount = 0
  let outCount = 0

  for (const edge of args.edges) {
    const source = String(edge.source ?? '')
    const target = String(edge.target ?? '')
    if (source !== selectedNode.id && target !== selectedNode.id) continue

    const rel = normalizeText(edge.kind) || 'relates_to'
    relationCounts.set(rel, (relationCounts.get(rel) ?? 0) + 1)

    const neighborId = source === selectedNode.id ? target : source
    const neighborNode = nodeMap.get(neighborId)
    const row =
      neighborMap.get(neighborId) ??
      ({
        id: neighborId,
        label: nodeDisplayLabel(neighborNode, neighborId),
        kind: neighborNode?.kind ?? 'unknown',
        links: 0,
        inCount: 0,
        outCount: 0,
        relations: [],
      } satisfies NeighborRow)

    row.links += 1
    if (source === selectedNode.id) {
      row.outCount += 1
      outCount += 1
    } else {
      row.inCount += 1
      inCount += 1
    }
    if (!row.relations.includes(rel)) row.relations.push(rel)
    neighborMap.set(neighborId, row)

    const eventYear = validYear(neighborNode?.year) ?? validYear(center?.year)
    const timelineKey = eventYear ? String(eventYear) : 'unknown'
    const timelineRow =
      timelineMap.get(timelineKey) ??
      ({
        key: timelineKey,
        year: eventYear,
        total: 0,
        supports: 0,
        challenges: 0,
        cites: 0,
        evidencedBy: 0,
        samples: [],
      } satisfies TimelineRow)

    timelineRow.total += 1
    if (rel === 'supports') timelineRow.supports += 1
    if (rel === 'challenges') timelineRow.challenges += 1
    if (rel === 'cites') timelineRow.cites += 1
    if (rel === 'evidenced_by') timelineRow.evidencedBy += 1
    if (timelineRow.samples.length < 2) {
      timelineRow.samples.push(`${rel} -> ${neighborNode?.label ?? neighborId}`)
    }
    timelineMap.set(timelineKey, timelineRow)
  }

  const relationRows = [...relationCounts.entries()]
    .map(([kind, count]) => ({ kind, count }))
    .sort((a, b) => b.count - a.count || a.kind.localeCompare(b.kind))

  const neighbors = [...neighborMap.values()].sort(compareNeighborRows)
  const childNeighbors = neighbors.filter((row) => row.outCount > 0)
  const parentNeighbors = neighbors.filter((row) => row.inCount > 0)
  const timeline = [...timelineMap.values()].sort((a, b) => {
    if (a.year === null && b.year === null) return a.key.localeCompare(b.key)
    if (a.year === null) return 1
    if (b.year === null) return -1
    return a.year - b.year
  })

  const years = timeline.map((row) => row.year).filter((year): year is number => year !== null)
  const timelineRange = years.length ? `${Math.min(...years)}-${Math.max(...years)}` : '-'
  const confidence = Number(center?.confidence)
  const qualityScore = Number.isFinite(confidence) ? Math.round(confidence * 100) : null

  return {
    center,
    relationRows,
    neighbors,
    childNeighbors,
    parentNeighbors,
    timeline,
    timelinePeak: timeline.reduce((max, row) => Math.max(max, row.total), 0),
    timelineRange,
    degree: inCount + outCount,
    relationDiversity: relationRows.length,
    neighborCount: neighborMap.size,
    inCount,
    outCount,
    qualityScore,
    raw: {
      selectedNode,
      center,
    },
  }
}
