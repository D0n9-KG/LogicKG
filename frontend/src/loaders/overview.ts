// frontend/src/loaders/overview.ts
import { apiGet } from '../api'
import { buildTextbookSnapshotGraph, type GraphSnapshotResponse } from './textbooks'
import type { GraphElement, GraphNodeData, GraphEdgeData } from '../state/types'

type NetworkNode = {
  id: string
  paper_source?: string
  title?: string
  doi?: string
  year?: number
  ingested?: boolean
  in_scope?: boolean
  phase1_quality_tier?: string
}

type NetworkEdge = {
  source: string
  target: string
  total_mentions?: number
  purpose_labels?: string[]
}

type NetworkResponse = { nodes: NetworkNode[]; edges: NetworkEdge[] }
type OverviewCommunityNode = {
  id: string
  label?: string
  kind?: string
  description?: string
  keywords?: string[]
  cluster_key?: string
  community_id?: string
  paper_id?: string
  paper_source?: string
  paper_title?: string
  step_type?: string
  chapter_id?: string
}

type OverviewCommunityEdge = {
  id: string
  source: string
  target: string
  kind?: string
  weight?: number
}

type OverviewCommunityResponse = {
  nodes?: OverviewCommunityNode[]
  edges?: OverviewCommunityEdge[]
}

type OverviewCommunityDetailMember = {
  member_id?: string
  member_kind?: string
  text?: string
  paper_id?: string
  paper_source?: string
  paper_title?: string
  step_type?: string
  source_chapter_id?: string
}

type OverviewCommunityDetailResponse = {
  community_id?: string
  title?: string
  summary?: string
  keywords?: string[]
  member_count?: number
  members?: OverviewCommunityDetailMember[]
}

type TextbookListResponse = {
  textbooks?: Array<{
    textbook_id?: string
    title?: string
  }>
}

const overviewGraphCache = new Map<string, GraphElement[]>()
const overviewGraphPending = new Map<string, Promise<GraphElement[]>>()
const overviewCommunity3DGraphCache = new Map<string, GraphElement[]>()
const overviewCommunity3DGraphPending = new Map<string, Promise<GraphElement[]>>()
const overviewCommunitySubgraphCache = new Map<string, GraphElement[]>()
const overviewCommunitySubgraphPending = new Map<string, Promise<GraphElement[]>>()
const OVERVIEW_TEXTBOOK_LIMIT = 4
export const OVERVIEW_GRAPH_DEFAULT_LIMIT_PAPERS = 340
export const OVERVIEW_GRAPH_DEFAULT_LIMIT_EDGES = 980
export const OVERVIEW_3D_DEFAULT_COMMUNITY_LIMIT = 400
export const OVERVIEW_3D_DEFAULT_MEMBER_LIMIT = 0
export const OVERVIEW_3D_DEFAULT_MAX_NODES = 400
export const OVERVIEW_3D_DEFAULT_MAX_EDGES = 620
export const OVERVIEW_3D_DEFAULT_INCLUDE_MEMBERS = false
export const OVERVIEW_COMMUNITY_SUBGRAPH_DEFAULT_MEMBER_LIMIT = 1200

function normalizeText(value: unknown): string {
  return String(value ?? '').trim()
}

function communityNodeId(communityId: string) {
  const normalized = normalizeText(communityId)
  return normalized.startsWith('community:') ? normalized : `community:${normalized}`
}

function communityClusterKey(communityId: string) {
  return communityNodeId(communityId)
}

function communityMemberKind(memberKind: unknown): GraphNodeData['kind'] {
  const normalized = normalizeText(memberKind).toLowerCase()
  if (normalized === 'logicstep' || normalized === 'logic_step' || normalized === 'logic') return 'logic'
  if (normalized === 'claim') return 'claim'
  if (normalized === 'knowledgeentity' || normalized === 'knowledge_entity' || normalized === 'entity') return 'entity'
  if (normalized === 'paper') return 'paper'
  return 'group'
}

function communityMemberNodeId(memberId: string, memberKind: unknown) {
  const normalizedId = normalizeText(memberId)
  const kind = communityMemberKind(memberKind)
  return normalizedId ? `${kind}:${normalizedId}` : ''
}

function communityMemberLabel(member: OverviewCommunityDetailMember) {
  const text = normalizeText(member.text)
  if (text) return text
  return normalizeText(member.paper_source) || normalizeText(member.paper_title) || normalizeText(member.member_id) || 'member'
}

function communityMemberDescription(member: OverviewCommunityDetailMember) {
  const text = normalizeText(member.text)
  const paperSource = normalizeText(member.paper_source)
  const paperTitle = normalizeText(member.paper_title)
  const stepType = normalizeText(member.step_type)
  const sourceChapterId = normalizeText(member.source_chapter_id)
  const parts = [paperSource, paperTitle, stepType, text || sourceChapterId].filter(Boolean)
  return parts.join(' | ')
}

function communitySummary(detail: OverviewCommunityDetailResponse) {
  const summary = normalizeText(detail.summary)
  if (summary) return summary
  const keywords = Array.isArray(detail.keywords) ? detail.keywords.map(normalizeText).filter(Boolean).slice(0, 8) : []
  if (keywords.length) return `Keywords: ${keywords.join(', ')}`
  return normalizeText(detail.title) || normalizeText(detail.community_id)
}

export function invalidateOverviewGraphCache() {
  overviewGraphCache.clear()
  overviewGraphPending.clear()
  overviewCommunity3DGraphCache.clear()
  overviewCommunity3DGraphPending.clear()
  overviewCommunitySubgraphCache.clear()
  overviewCommunitySubgraphPending.clear()
  window.dispatchEvent(new CustomEvent('overview-community-3d-invalidate'))
}

export function invalidateOverviewCommunity3DGraphCache() {
  overviewCommunity3DGraphCache.clear()
  overviewCommunity3DGraphPending.clear()
  overviewCommunitySubgraphCache.clear()
  overviewCommunitySubgraphPending.clear()
  window.dispatchEvent(new CustomEvent('overview-community-3d-invalidate'))
}

export async function loadOverviewGraph(
  limitPapers = OVERVIEW_GRAPH_DEFAULT_LIMIT_PAPERS,
  limitEdges = OVERVIEW_GRAPH_DEFAULT_LIMIT_EDGES,
  options: { force?: boolean; includeTextbooks?: boolean } = {},
): Promise<GraphElement[]> {
  const includeTextbooks = options.includeTextbooks !== false
  const cacheKey = `${limitPapers}:${limitEdges}:${includeTextbooks ? 'with-textbooks' : 'papers-only'}`
  if (options.force) {
    overviewGraphCache.delete(cacheKey)
    overviewGraphPending.delete(cacheKey)
  }
  const cached = overviewGraphCache.get(cacheKey)
  if (cached) return cached

  const pending = overviewGraphPending.get(cacheKey)
  if (pending) return pending

  const qs = new URLSearchParams({
    limit_papers: String(limitPapers),
    limit_edges: String(limitEdges),
  })
  const request = apiGet<NetworkResponse>(`/graph/network?${qs}`)
    .then(async (res) => {
      const nodeMap = new Map<string, GraphElement>()
      const edgeMap = new Map<string, GraphElement>()

      for (const n of res.nodes ?? []) {
        nodeMap.set(n.id, {
          group: 'nodes',
          data: {
            id: n.id,
            label: n.paper_source ?? n.title ?? n.doi ?? n.id,
            description: n.title ?? undefined,
            kind: 'paper',
            paperId: n.id,
            qualityTier: n.phase1_quality_tier,
            ingested: n.ingested,
            inScope: n.in_scope,
            year: typeof n.year === 'number' ? n.year : undefined,
          } satisfies GraphNodeData,
        })
      }

      for (const e of res.edges ?? []) {
        edgeMap.set(`cites:${e.source}->${e.target}`, {
          group: 'edges',
          data: {
            id: `cites:${e.source}->${e.target}`,
            source: e.source,
            target: e.target,
            kind: 'cites',
            totalMentions: e.total_mentions,
            purposeLabels: e.purpose_labels,
            weight: Math.min(1, (e.total_mentions ?? 0) / 20),
          } satisfies GraphEdgeData,
        })
      }

      if (includeTextbooks) {
        try {
          const textbooks = await apiGet<TextbookListResponse>(`/textbooks?limit=${OVERVIEW_TEXTBOOK_LIMIT}`)
          const textbookIds = (textbooks.textbooks ?? [])
            .map((row) => String(row.textbook_id ?? '').trim())
            .filter(Boolean)
            .slice(0, OVERVIEW_TEXTBOOK_LIMIT)
          const textbookSnapshots = await Promise.allSettled(
            textbookIds.map((textbookId) =>
              apiGet(
                `/textbooks/${encodeURIComponent(textbookId)}/graph?entity_limit=120&edge_limit=180`,
              ).then((snapshot) => ({ textbookId, snapshot })),
            ),
          )
          for (const result of textbookSnapshots) {
            if (result.status !== 'fulfilled') continue
            const textbookElements = buildTextbookSnapshotGraph(result.value.snapshot as GraphSnapshotResponse, result.value.textbookId)
            for (const element of textbookElements) {
              if (element.group === 'nodes') nodeMap.set(element.data.id, element)
              else edgeMap.set(element.data.id, element)
            }
          }
        } catch {
          // keep the overview usable if textbook graph loading is unavailable
        }
      }

      const elements = [...nodeMap.values(), ...edgeMap.values()]
      overviewGraphCache.set(cacheKey, elements)
      return elements
    })
    .finally(() => {
      overviewGraphPending.delete(cacheKey)
    })

  overviewGraphPending.set(cacheKey, request)
  return request
}

export async function loadOverviewCommunity3DGraph(options: {
  communityLimit?: number
  memberLimitPerCommunity?: number
  maxNodes?: number
  maxEdges?: number
  includeMembers?: boolean
  force?: boolean
} = {}): Promise<GraphElement[]> {
  const includeMembers = options.includeMembers ?? OVERVIEW_3D_DEFAULT_INCLUDE_MEMBERS
  const communityLimit = Math.max(1, Math.min(800, Math.round(options.communityLimit ?? OVERVIEW_3D_DEFAULT_COMMUNITY_LIMIT)))
  const memberLimitPerCommunity = Math.max(0, Math.min(24, Math.round(options.memberLimitPerCommunity ?? OVERVIEW_3D_DEFAULT_MEMBER_LIMIT)))
  const maxNodes = Math.max(8, Math.min(800, Math.round(options.maxNodes ?? OVERVIEW_3D_DEFAULT_MAX_NODES)))
  const maxEdges = Math.max(8, Math.min(1600, Math.round(options.maxEdges ?? OVERVIEW_3D_DEFAULT_MAX_EDGES)))
  const cacheKey = `${communityLimit}:${memberLimitPerCommunity}:${maxNodes}:${maxEdges}:${includeMembers ? 'members' : 'communities'}`

  if (options.force) {
    overviewCommunity3DGraphCache.delete(cacheKey)
    overviewCommunity3DGraphPending.delete(cacheKey)
  }

  const cached = overviewCommunity3DGraphCache.get(cacheKey)
  if (cached) return cached

  const pending = overviewCommunity3DGraphPending.get(cacheKey)
  if (pending) return pending

  const qs = new URLSearchParams({
    community_limit: String(communityLimit),
    ...(includeMembers ? { member_limit_per_community: String(memberLimitPerCommunity) } : {}),
    max_nodes: String(maxNodes),
    max_edges: String(maxEdges),
    include_members: includeMembers ? 'true' : 'false',
  })

  const request = apiGet<OverviewCommunityResponse>(`/community/overview-graph?${qs}`)
    .then((res) => {
      const nodeMap = new Map<string, GraphElement>()
      const edgeMap = new Map<string, GraphElement>()

      for (const node of res.nodes ?? []) {
        const id = String(node.id ?? '').trim()
        if (!id) continue
        nodeMap.set(id, {
          group: 'nodes',
          data: {
            id,
            label: String(node.label ?? id).trim() || id,
            description: String(node.description ?? '').trim() || undefined,
            kind: String(node.kind ?? 'community').trim() || 'community',
            keywords: Array.isArray(node.keywords)
              ? node.keywords.map((value) => String(value ?? '').trim()).filter(Boolean)
              : undefined,
            clusterKey: String(node.cluster_key ?? '').trim() || undefined,
            communityId: String(node.community_id ?? '').trim() || undefined,
            paperId: String(node.paper_id ?? '').trim() || undefined,
            paperSource: String(node.paper_source ?? '').trim() || undefined,
            paperTitle: String(node.paper_title ?? '').trim() || undefined,
            stepType: String(node.step_type ?? '').trim() || undefined,
            chapterId: String(node.chapter_id ?? '').trim() || undefined,
          } satisfies GraphNodeData,
        })
      }

      for (const edge of res.edges ?? []) {
        const id = String(edge.id ?? '').trim()
        const source = String(edge.source ?? '').trim()
        const target = String(edge.target ?? '').trim()
        if (!id || !source || !target) continue
        if (!nodeMap.has(source) || !nodeMap.has(target)) continue
        edgeMap.set(id, {
          group: 'edges',
          data: {
            id,
            source,
            target,
            kind: String(edge.kind ?? 'contains').trim() || 'contains',
            weight: Math.min(1, Math.max(0.08, Number(edge.weight ?? 0.5))),
          } satisfies GraphEdgeData,
        })
      }

      const elements = [...nodeMap.values(), ...edgeMap.values()]
      overviewCommunity3DGraphCache.set(cacheKey, elements)
      return elements
    })
    .finally(() => {
      overviewCommunity3DGraphPending.delete(cacheKey)
    })

  overviewCommunity3DGraphPending.set(cacheKey, request)
  return request
}

export function resolveOverviewExpandedCommunityId(elements: GraphElement[]): string | null {
  const nodes = elements.filter((element) => element.group === 'nodes').map((element) => element.data)
  const edges = elements.filter((element) => element.group === 'edges').map((element) => element.data)
  const communityNodes = nodes.filter((node) => node.kind === 'community')
  if (communityNodes.length !== 1) return null

  const communityNode = communityNodes[0]
  const communityId =
    normalizeText(communityNode.communityId) ||
    (communityNode.id.startsWith('community:') ? communityNode.id.slice('community:'.length) : '')
  if (!communityId) return null

  const expectedCommunityNodeId = communityNodeId(communityId)
  if (communityNode.id !== expectedCommunityNodeId) return null

  const memberNodes = nodes.filter((node) => node.id !== communityNode.id)
  if (!memberNodes.length) return communityId

  const validMembers = memberNodes.every((node) => {
    const nodeCommunityId = normalizeText(node.communityId)
    const clusterKey = normalizeText(node.clusterKey)
    return nodeCommunityId === communityId && (!clusterKey || clusterKey === expectedCommunityNodeId)
  })
  if (!validMembers) return null

  const validEdges = edges.every((edge) => {
    if (edge.kind !== 'contains') return false
    return edge.source === expectedCommunityNodeId || edge.target === expectedCommunityNodeId
  })
  if (!validEdges) return null

  return communityId
}

export async function loadOverviewCommunitySubgraph(
  communityId: string,
  options: { force?: boolean; memberLimit?: number } = {},
): Promise<GraphElement[]> {
  const communityKey = normalizeText(communityId)
  if (!communityKey) return []

  const memberLimit = Math.max(
    1,
    Math.min(2000, Math.round(options.memberLimit ?? OVERVIEW_COMMUNITY_SUBGRAPH_DEFAULT_MEMBER_LIMIT)),
  )
  const cacheKey = `${communityKey}:${memberLimit}`

  if (options.force) {
    overviewCommunitySubgraphCache.delete(cacheKey)
    overviewCommunitySubgraphPending.delete(cacheKey)
  }

  const cached = overviewCommunitySubgraphCache.get(cacheKey)
  if (cached) return cached

  const pending = overviewCommunitySubgraphPending.get(cacheKey)
  if (pending) return pending

  const request = apiGet<OverviewCommunityDetailResponse>(
    `/community/${encodeURIComponent(communityKey)}?member_limit=${memberLimit}`,
  )
    .then((detail) => {
      const normalizedCommunityId = normalizeText(detail.community_id) || communityKey
      const clusterKey = communityClusterKey(normalizedCommunityId)
      const communityLabel = normalizeText(detail.title) || normalizedCommunityId
      const communityDescription = communitySummary(detail)
      const memberCount = Number(detail.member_count)

      const nodeMap = new Map<string, GraphElement>()
      const edgeMap = new Map<string, GraphElement>()

      nodeMap.set(clusterKey, {
        group: 'nodes',
        data: {
          id: clusterKey,
          label: communityLabel,
          description: communityDescription || undefined,
          kind: 'community',
          communityId: normalizedCommunityId,
          clusterKey,
          keywords: Array.isArray(detail.keywords)
            ? detail.keywords.map((value) => String(value ?? '').trim()).filter(Boolean)
            : undefined,
          mentions: Number.isFinite(memberCount) ? memberCount : undefined,
        } satisfies GraphNodeData,
      })

      for (const member of detail.members ?? []) {
        const memberId = normalizeText(member.member_id)
        if (!memberId) continue
        const id = communityMemberNodeId(memberId, member.member_kind)
        if (!id) continue
        const kind = communityMemberKind(member.member_kind)
        const label = communityMemberLabel(member)
        const description = communityMemberDescription(member)

        nodeMap.set(id, {
          group: 'nodes',
          data: {
            id,
            label: label || memberId,
            description: description || undefined,
            kind,
            communityId: normalizedCommunityId,
            clusterKey,
            paperId: normalizeText(member.paper_id) || undefined,
            paperSource: normalizeText(member.paper_source) || undefined,
            paperTitle: normalizeText(member.paper_title) || undefined,
            stepType: normalizeText(member.step_type) || undefined,
            chapterId: normalizeText(member.source_chapter_id) || undefined,
          } satisfies GraphNodeData,
        })

        edgeMap.set(`contains:${clusterKey}->${id}`, {
          group: 'edges',
          data: {
            id: `contains:${clusterKey}->${id}`,
            source: clusterKey,
            target: id,
            kind: 'contains',
            weight: 1,
          } satisfies GraphEdgeData,
        })
      }

      const elements = [...nodeMap.values(), ...edgeMap.values()]
      overviewCommunitySubgraphCache.set(cacheKey, elements)
      return elements
    })
    .finally(() => {
      overviewCommunitySubgraphPending.delete(cacheKey)
    })

  overviewCommunitySubgraphPending.set(cacheKey, request)
  return request
}
