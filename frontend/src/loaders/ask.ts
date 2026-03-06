import type { GraphElement, GraphNodeData, GraphEdgeData } from '../state/types'

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

export type GraphContextRow = {
  paper_source?: string
  paper_title?: string
  cited_doi?: string
  cited_title?: string
  total_mentions?: number
  purpose_labels?: string[]
}

export type StructuredLogicRow = {
  paper_source?: string
  paper_title?: string
  step_type?: string
  summary?: string
}

export type StructuredClaimRow = {
  claim_id?: string
  paper_source?: string
  paper_title?: string
  step_type?: string
  text?: string
  confidence?: number
}

export type StructuredKnowledge = {
  logic_steps?: StructuredLogicRow[]
  claims?: StructuredClaimRow[]
}

export type AskApiResponse = {
  answer?: string
  evidence?: EvidenceRow[]
  graph_context?: GraphContextRow[]
  structured_knowledge?: StructuredKnowledge | null
  retrieval_mode?: string
  message?: string
  insufficient_scope_evidence?: boolean
}

function norm(v: string | null | undefined): string {
  return String(v ?? '')
    .replace(/\s+/g, ' ')
    .trim()
}

function short(v: string | null | undefined, max = 40): string {
  const text = norm(v)
  return text.length <= max ? text : `${text.slice(0, max - 3)}...`
}

function sourceFromMdPath(mdPath: string | null | undefined): string {
  const raw = norm(mdPath)
  if (!raw) return ''
  const parts = raw.replace(/\\/g, '/').split('/').filter(Boolean)
  if (!parts.length) return raw
  const last = parts[parts.length - 1]
  if (/\.md$/i.test(last) && parts.length >= 2) return parts[parts.length - 2]
  return last
}

function lineNumber(value: unknown): number | null {
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  const rounded = Math.round(n)
  return rounded > 0 ? rounded : null
}

function paperNodePresentation(row: Pick<EvidenceRow, 'paper_title' | 'paper_source' | 'paper_id' | 'md_path'>): {
  label: string
  description: string
  priority: number
} {
  const title = norm(row.paper_title)
  const source = norm(row.paper_source) || sourceFromMdPath(row.md_path)
  const paperId = norm(row.paper_id)
  const mdPath = norm(row.md_path)
  if (title) return { label: title, description: title, priority: 4 }
  if (source) return { label: source, description: source, priority: 3 }
  if (paperId) return { label: paperId, description: paperId, priority: 2 }
  if (mdPath) return { label: short(mdPath, 42), description: mdPath, priority: 1 }
  return { label: 'paper', description: 'paper', priority: 0 }
}

export function buildEvidenceNodeId(row: EvidenceRow, index: number): string {
  const source = norm(row.paper_source) || sourceFromMdPath(row.md_path) || norm(row.paper_id) || 'unknown'
  const sourceKey = encodeURIComponent(source)
  const start = lineNumber(row.start_line) ?? 0
  const end = lineNumber(row.end_line) ?? 0
  return `evidence:${sourceKey}:${start}:${end}:${Math.max(1, index + 1)}`
}

export function buildAskGraph(res: AskApiResponse): GraphElement[] {
  const nodeMap = new Map<string, GraphNodeData>()
  const edgeMap = new Map<string, GraphEdgeData>()
  const sourceToPaperNodeId = new Map<string, string>()
  const sourceToPaperTitle = new Map<string, string>()
  const paperNodePriority = new Map<string, number>()

  const upsertPaperNode = (
    nodeId: string,
    args: { label: string; description: string; priority: number; paperId?: string },
  ) => {
    const existing = nodeMap.get(nodeId)
    const prevPriority = paperNodePriority.get(nodeId) ?? -1
    if (!existing || args.priority >= prevPriority) {
      nodeMap.set(nodeId, {
        id: nodeId,
        label: args.label,
        kind: 'paper',
        paperId: args.paperId || existing?.paperId,
        description: args.description || existing?.description,
      })
      paperNodePriority.set(nodeId, args.priority)
      return
    }
    if (args.paperId && !existing.paperId) {
      nodeMap.set(nodeId, { ...existing, paperId: args.paperId })
    }
  }

  for (const [index, ev] of (res.evidence ?? []).entries()) {
    const paperId = norm(ev.paper_id)
    const source = norm(ev.paper_source) || sourceFromMdPath(ev.md_path)
    const title = norm(ev.paper_title)
    const mdPath = norm(ev.md_path)
    const nodeId = paperId ? `paper:${paperId}` : source ? `paper_source:${source}` : mdPath ? `paper_file:${mdPath}` : ''
    if (!nodeId) continue

    const presentation = paperNodePresentation(ev)
    upsertPaperNode(nodeId, {
      label: presentation.label,
      description: presentation.description,
      priority: presentation.priority,
      paperId: paperId || undefined,
    })
    if (source) sourceToPaperNodeId.set(source, nodeId)
    if (source && title) sourceToPaperTitle.set(source, title)

    const start = lineNumber(ev.start_line)
    const end = lineNumber(ev.end_line)
    const lineRange =
      start !== null && end !== null
        ? `${start}-${end}`
        : start !== null
          ? String(start)
          : end !== null
            ? String(end)
            : ''
    const evidenceNodeId = buildEvidenceNodeId(ev, index)
    const evidenceLabel = lineRange ? `E${index + 1} ${lineRange}` : `E${index + 1}`
    const evidenceDescription = norm(ev.snippet || mdPath || source || paperId || 'evidence')
    nodeMap.set(evidenceNodeId, {
      id: evidenceNodeId,
      label: evidenceLabel,
      kind: 'entity',
      description: evidenceDescription,
      paperId: paperId || undefined,
    })
    edgeMap.set(`${nodeId}->${evidenceNodeId}`, {
      id: `${nodeId}->${evidenceNodeId}`,
      source: nodeId,
      target: evidenceNodeId,
      kind: 'evidenced_by',
      weight: Number.isFinite(Number(ev.score)) ? Math.max(0.2, Math.min(1, Number(ev.score))) : 0.4,
    })
  }

  for (const row of res.graph_context ?? []) {
    const source = norm(row.paper_source)
    const sourceNodeId = source ? sourceToPaperNodeId.get(source) ?? `paper_source:${source}` : ''
    if (sourceNodeId) {
      const title = norm(row.paper_title) || sourceToPaperTitle.get(source) || ''
      upsertPaperNode(sourceNodeId, {
        label: title || source,
        description: title || source,
        priority: title ? 4 : 3,
      })
      if (title && source) sourceToPaperTitle.set(source, title)
    }

    const citationLabel = norm(row.cited_title || row.cited_doi || 'citation')
    const citationNodeId = `citation:${norm(row.cited_doi || row.cited_title || `${source}:${citationLabel}`)}`
    nodeMap.set(citationNodeId, {
      id: citationNodeId,
      label: short(citationLabel, 42),
      kind: 'citation',
      description: citationLabel,
    })
    if (sourceNodeId) {
      edgeMap.set(`${sourceNodeId}->${citationNodeId}`, {
        id: `${sourceNodeId}->${citationNodeId}`,
        source: sourceNodeId,
        target: citationNodeId,
        kind: 'cites',
        weight: 0.4,
      })
    }
  }

  const logicByPaperAndType = new Map<string, string>()
  for (const step of res.structured_knowledge?.logic_steps ?? []) {
    const source = norm(step.paper_source)
    const sourceNodeId = source ? sourceToPaperNodeId.get(source) ?? `paper_source:${source}` : ''
    if (!sourceNodeId) continue
    const title = norm(step.paper_title) || sourceToPaperTitle.get(source) || ''
    upsertPaperNode(sourceNodeId, {
      label: title || source,
      description: title || source,
      priority: title ? 4 : 3,
    })
    if (title && source) sourceToPaperTitle.set(source, title)

    const key = `${source}:${step.step_type ?? 'logic'}:${step.summary ?? ''}`
    const nodeId = `logic:${key}`
    const logicSummary = norm(step.summary || step.step_type || 'logic')
    nodeMap.set(nodeId, {
      id: nodeId,
      label: short(logicSummary, 38),
      kind: 'logic',
      description: logicSummary,
    })
    edgeMap.set(`${sourceNodeId}->${nodeId}`, {
      id: `${sourceNodeId}->${nodeId}`,
      source: sourceNodeId,
      target: nodeId,
      kind: 'contains',
      weight: 0.5,
    })
    logicByPaperAndType.set(`${source}:${step.step_type ?? ''}`, nodeId)
  }

  for (const claim of res.structured_knowledge?.claims ?? []) {
    const source = norm(claim.paper_source)
    const sourceNodeId = source ? sourceToPaperNodeId.get(source) ?? `paper_source:${source}` : ''
    if (!sourceNodeId) continue
    const title = norm(claim.paper_title) || sourceToPaperTitle.get(source) || ''
    upsertPaperNode(sourceNodeId, {
      label: title || source,
      description: title || source,
      priority: title ? 4 : 3,
    })
    if (title && source) sourceToPaperTitle.set(source, title)

    const key = norm(claim.claim_id || claim.text || `${source}:${claim.step_type ?? ''}`)
    const claimNodeId = `claim:${key}`
    const claimText = norm(claim.text || claim.claim_id || 'claim')
    nodeMap.set(claimNodeId, {
      id: claimNodeId,
      label: short(claimText, 38),
      kind: 'claim',
      description: claimText,
      confidence: claim.confidence,
    })
    edgeMap.set(`${sourceNodeId}->${claimNodeId}`, {
      id: `${sourceNodeId}->${claimNodeId}`,
      source: sourceNodeId,
      target: claimNodeId,
      kind: 'supports',
      weight: 0.5,
    })

    const logicNodeId = logicByPaperAndType.get(`${source}:${claim.step_type ?? ''}`)
    if (logicNodeId) {
      edgeMap.set(`${logicNodeId}->${claimNodeId}`, {
        id: `${logicNodeId}->${claimNodeId}`,
        source: logicNodeId,
        target: claimNodeId,
        kind: 'supports',
        weight: 0.5,
      })
    }
  }

  const nodes: GraphElement[] = Array.from(nodeMap.values()).map((data) => ({ group: 'nodes', data }))
  const edges: GraphElement[] = Array.from(edgeMap.values()).map((data) => ({ group: 'edges', data }))
  return [...nodes, ...edges]
}

function hasNodes(elements: GraphElement[]): boolean {
  return elements.some((item) => item.group === 'nodes')
}

export function resolveAskGraph(res: AskApiResponse, fallback: GraphElement[]): GraphElement[] {
  const askGraph = buildAskGraph(res)
  if (hasNodes(askGraph)) return askGraph
  return fallback
}
