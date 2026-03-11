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

export type QueryPlanRow = {
  intent?: string
  retrieval_plan?: string
  main_query?: string
  paper_query?: string
  textbook_query?: string
  community_query?: string
  confidence?: number
  reason?: string
}

export type StructuredEvidenceRow = {
  kind?: string
  source_id?: string
  community_id?: string
  text?: string
  score?: number
  paper_source?: string
  paper_id?: string
  source_kind?: string
  source_ref_id?: string
  entity_id?: string
  textbook_id?: string
  chapter_id?: string
  member_ids?: string[]
  member_kinds?: string[]
  keyword_texts?: string[]
  evidence_event_id?: string
  evidence_event_type?: string
}

export type GroundingRow = {
  source_kind?: string
  source_id?: string
  quote?: string
  paper_source?: string
  paper_id?: string
  md_path?: string
  chunk_id?: string
  textbook_id?: string
  chapter_id?: string
  start_line?: number
  end_line?: number
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

export type AskApiResponse = {
  answer?: string
  evidence?: EvidenceRow[]
  fusion_evidence?: FusionEvidenceRow[]
  dual_evidence_coverage?: boolean
  graph_context?: GraphContextRow[]
  structured_knowledge?: StructuredKnowledge | null
  query_plan?: QueryPlanRow | null
  structured_evidence?: StructuredEvidenceRow[]
  grounding?: GroundingRow[]
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

function textbookNodeId(textbookId: string): string {
  return `textbook:${textbookId}`
}

function chapterNodeId(chapterId: string): string {
  return `chapter:${chapterId}`
}

function entityNodeId(entityId: string): string {
  return `entity:${entityId}`
}

function communityNodeId(communityId: string): string {
  return `community:${communityId}`
}

function claimNodeId(claimId: string): string {
  return `claim:${claimId}`
}

function logicNodeId(logicId: string): string {
  return `logic:${logicId}`
}

function evidenceSourceKey(row: Pick<EvidenceRow, 'paper_source' | 'paper_id' | 'md_path'>): string {
  const source = norm(row.paper_source) || sourceFromMdPath(row.md_path)
  const paperId = norm(row.paper_id)
  return paperId || source
}

function evidenceNodeIdForGrounding(row: GroundingRow, evidenceNodeIdsBySource: Map<string, string[]>): string[] {
  const paperSource = norm(row.paper_source)
  const paperId = norm(row.paper_id)
  const mdSource = sourceFromMdPath(row.md_path)
  const keys = [paperId, paperSource, mdSource].filter(Boolean)
  for (const key of keys) {
    const matches = evidenceNodeIdsBySource.get(key)
    if (matches?.length) return matches
  }
  return []
}

function normalizedMemberKind(kind: string): string {
  const value = norm(kind).toLowerCase()
  if (!value) return 'entity'
  if (value === 'logic_step') return 'logic'
  return value
}

function buildMemberNodeId(memberId: string, memberKind: string): string {
  const kind = normalizedMemberKind(memberKind)
  if (kind === 'claim') return claimNodeId(memberId)
  if (kind === 'logic') return logicNodeId(memberId)
  if (kind === 'entity') return entityNodeId(memberId)
  if (kind === 'paper') return `paper:${memberId}`
  if (kind === 'textbook') return textbookNodeId(memberId)
  if (kind === 'chapter') return chapterNodeId(memberId)
  if (kind === 'community') return communityNodeId(memberId)
  return `${kind}:${memberId}`
}

function chapterLabel(row: FusionEvidenceRow): string {
  const title = norm(row.chapter_title)
  const chapterId = norm(row.chapter_id || row.source_chapter_id)
  const chapterNum = Number(row.chapter_num)
  if (Number.isFinite(chapterNum)) {
    return title ? `Ch.${Math.round(chapterNum)} ${title}` : `Ch.${Math.round(chapterNum)}`
  }
  return title || chapterId || 'chapter'
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
  const evidenceNodeIdsBySource = new Map<string, string[]>()
  const claimNodeById = new Map<string, string>()
  const claimToLogicNodeId = new Map<string, string>()
  const communityNodeById = new Map<string, string>()

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

    const evidenceKeys = [evidenceSourceKey(ev), paperId, source].filter(Boolean)
    for (const key of evidenceKeys) {
      const existing = evidenceNodeIdsBySource.get(key) ?? []
      existing.push(evidenceNodeId)
      evidenceNodeIdsBySource.set(key, existing)
    }
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
    if (claim.claim_id) claimNodeById.set(norm(claim.claim_id), claimNodeId)
    edgeMap.set(`${sourceNodeId}->${claimNodeId}`, {
      id: `${sourceNodeId}->${claimNodeId}`,
      source: sourceNodeId,
      target: claimNodeId,
      kind: 'supports',
      weight: 0.5,
    })

    const logicNodeId = logicByPaperAndType.get(`${source}:${claim.step_type ?? ''}`)
    if (logicNodeId) {
      if (claim.claim_id) claimToLogicNodeId.set(norm(claim.claim_id), logicNodeId)
      edgeMap.set(`${logicNodeId}->${claimNodeId}`, {
        id: `${logicNodeId}->${claimNodeId}`,
        source: logicNodeId,
        target: claimNodeId,
        kind: 'supports',
        weight: 0.5,
      })
    }
  }

  for (const row of res.structured_evidence ?? []) {
    const kind = norm(row.kind).toLowerCase()
    if (kind !== 'community') continue

    const communityId = norm(row.community_id || row.source_id)
    if (!communityId) continue

    const nodeId = communityNodeId(communityId)
    communityNodeById.set(communityId, nodeId)

    const communityText = norm(row.text || row.community_id || row.source_id || 'community')
    const keywordText = (row.keyword_texts ?? []).map((value) => norm(value)).filter(Boolean).join(', ')
    nodeMap.set(nodeId, {
      id: nodeId,
      label: short(communityText, 38),
      kind: 'community',
      description: keywordText ? `${communityText} | ${keywordText}` : communityText,
      communityId,
      paperId: norm(row.paper_id) || undefined,
      textbookId: norm(row.textbook_id) || undefined,
      chapterId: norm(row.chapter_id) || undefined,
    })

    const memberIds = row.member_ids ?? []
    const memberKinds = row.member_kinds ?? []
    memberIds.forEach((memberIdRaw, index) => {
      const memberId = norm(memberIdRaw)
      const memberKind = normalizedMemberKind(memberKinds[index] ?? '')
      if (!memberId) return

      const targetNodeId = buildMemberNodeId(memberId, memberKind)
      const existing = nodeMap.get(targetNodeId)
      if (!existing) {
        nodeMap.set(targetNodeId, {
          id: targetNodeId,
          label: short(memberId, 38),
          kind: memberKind,
          description: memberId,
          communityId,
        })
      }

      edgeMap.set(`${nodeId}->${targetNodeId}`, {
        id: `${nodeId}->${targetNodeId}`,
        source: nodeId,
        target: targetNodeId,
        kind: 'contains',
        weight: Number.isFinite(Number(row.score)) ? Math.max(0.35, Math.min(1, Number(row.score))) : 0.55,
      })
    })
  }

  for (const row of res.grounding ?? []) {
    const sourceKind = normalizedMemberKind(String(row.source_kind ?? ''))
    const sourceId = norm(row.source_id)
    if (!sourceId) continue

    const nodeId =
      sourceKind === 'community'
        ? communityNodeById.get(sourceId) ?? communityNodeId(sourceId)
        : buildMemberNodeId(sourceId, sourceKind)
    const existing = nodeMap.get(nodeId)
    if (!existing) continue
    const quote = norm(row.quote)
    if (!quote) continue
    nodeMap.set(nodeId, {
      ...existing,
      description: existing.description ? `${existing.description} | ${quote}` : quote,
    })

    const evidenceNodeIds = evidenceNodeIdForGrounding(row, evidenceNodeIdsBySource)
    for (const evidenceNodeId of evidenceNodeIds) {
      edgeMap.set(`${nodeId}->${evidenceNodeId}`, {
        id: `${nodeId}->${evidenceNodeId}`,
        source: nodeId,
        target: evidenceNodeId,
        kind: 'evidenced_by',
        weight: 0.6,
      })
    }
  }

  for (const fusion of res.fusion_evidence ?? []) {
    const paperSource = norm(fusion.paper_source)
    const paperId = norm(fusion.paper_id)
    const paperNodeId =
      (paperSource ? sourceToPaperNodeId.get(paperSource) : undefined)
      || (paperId ? `paper:${paperId}` : '')
      || (paperSource ? `paper_source:${paperSource}` : '')

    if (paperNodeId) {
      const title = sourceToPaperTitle.get(paperSource) || paperSource || paperId || 'paper'
      upsertPaperNode(paperNodeId, {
        label: title,
        description: title,
        priority: sourceToPaperTitle.has(paperSource) ? 4 : 3,
        paperId: paperId || undefined,
      })
      if (paperSource) sourceToPaperNodeId.set(paperSource, paperNodeId)
    }

    const textbookId = norm(fusion.textbook_id)
    const textbookTitle = norm(fusion.textbook_title)
    const chapterId = norm(fusion.chapter_id || fusion.source_chapter_id)
    const entityId = norm(fusion.entity_id)

    if (textbookId) {
      nodeMap.set(textbookNodeId(textbookId), {
        id: textbookNodeId(textbookId),
        label: textbookTitle || textbookId,
        kind: 'textbook',
        description: textbookTitle || textbookId,
        textbookId,
        clusterKey: textbookNodeId(textbookId),
      })
    }

    if (chapterId) {
      nodeMap.set(chapterNodeId(chapterId), {
        id: chapterNodeId(chapterId),
        label: chapterLabel(fusion),
        kind: 'chapter',
        description: [textbookTitle, norm(fusion.chapter_title), chapterId].filter(Boolean).join(' | '),
        textbookId: textbookId || undefined,
        chapterId,
        clusterKey: textbookId ? textbookNodeId(textbookId) : chapterNodeId(chapterId),
      })
      if (textbookId) {
        edgeMap.set(`${textbookNodeId(textbookId)}->${chapterNodeId(chapterId)}`, {
          id: `${textbookNodeId(textbookId)}->${chapterNodeId(chapterId)}`,
          source: textbookNodeId(textbookId),
          target: chapterNodeId(chapterId),
          kind: 'contains',
          weight: 0.82,
        })
      }
    }

    if (entityId) {
      nodeMap.set(entityNodeId(entityId), {
        id: entityNodeId(entityId),
        label: norm(fusion.entity_name) || entityId,
        kind: 'entity',
        description: [norm(fusion.entity_type), norm(fusion.description), norm(fusion.evidence_quote)].filter(Boolean).join(' | ') || undefined,
        textbookId: textbookId || undefined,
        chapterId: chapterId || undefined,
        clusterKey: chapterId ? chapterNodeId(chapterId) : textbookId ? textbookNodeId(textbookId) : undefined,
      })
      if (chapterId) {
        edgeMap.set(`${chapterNodeId(chapterId)}->${entityNodeId(entityId)}`, {
          id: `${chapterNodeId(chapterId)}->${entityNodeId(entityId)}`,
          source: chapterNodeId(chapterId),
          target: entityNodeId(entityId),
          kind: 'contains',
          weight: 0.76,
        })
      }
    }

    const logicNodeId = paperSource ? logicByPaperAndType.get(`${paperSource}:${fusion.step_type ?? ''}`) : undefined
    if (entityId && logicNodeId) {
      edgeMap.set(`${logicNodeId}->${entityNodeId(entityId)}`, {
        id: `${logicNodeId}->${entityNodeId(entityId)}`,
        source: logicNodeId,
        target: entityNodeId(entityId),
        kind: 'maps_to',
        weight: Number.isFinite(Number(fusion.score)) ? Math.max(0.35, Math.min(1, Number(fusion.score))) : 0.56,
      })
    } else if (entityId && paperNodeId) {
      edgeMap.set(`${paperNodeId}->${entityNodeId(entityId)}`, {
        id: `${paperNodeId}->${entityNodeId(entityId)}`,
        source: paperNodeId,
        target: entityNodeId(entityId),
        kind: 'maps_to',
        weight: Number.isFinite(Number(fusion.score)) ? Math.max(0.35, Math.min(1, Number(fusion.score))) : 0.5,
      })
    }
  }

  const nodes: GraphElement[] = Array.from(nodeMap.values())
    .sort((left, right) => {
      const rank = (node: GraphNodeData) => {
        if (node.kind === 'community') return 0
        if (String(node.id).startsWith('evidence:')) return 2
        return 1
      }
      return rank(left) - rank(right)
    })
    .map((data) => ({ group: 'nodes', data }))
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
