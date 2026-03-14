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
const OVERVIEW_TEXTBOOK_LIMIT = 4

export function invalidateOverviewGraphCache() {
  overviewGraphCache.clear()
  overviewGraphPending.clear()
  overviewCommunity3DGraphCache.clear()
  overviewCommunity3DGraphPending.clear()
  window.dispatchEvent(new CustomEvent('overview-community-3d-invalidate'))
}

export function invalidateOverviewCommunity3DGraphCache() {
  overviewCommunity3DGraphCache.clear()
  overviewCommunity3DGraphPending.clear()
  window.dispatchEvent(new CustomEvent('overview-community-3d-invalidate'))
}

export async function loadOverviewGraph(
  limitPapers = 200,
  limitEdges = 600,
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
  force?: boolean
} = {}): Promise<GraphElement[]> {
  const communityLimit = Math.max(1, Math.min(80, Math.round(options.communityLimit ?? 18)))
  const memberLimitPerCommunity = Math.max(1, Math.min(24, Math.round(options.memberLimitPerCommunity ?? 6)))
  const maxNodes = Math.max(8, Math.min(800, Math.round(options.maxNodes ?? 160)))
  const maxEdges = Math.max(8, Math.min(1600, Math.round(options.maxEdges ?? 240)))
  const cacheKey = `${communityLimit}:${memberLimitPerCommunity}:${maxNodes}:${maxEdges}`

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
    member_limit_per_community: String(memberLimitPerCommunity),
    max_nodes: String(maxNodes),
    max_edges: String(maxEdges),
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
