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
