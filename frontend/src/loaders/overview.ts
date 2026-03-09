// frontend/src/loaders/overview.ts
import { apiGet } from '../api'
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

const overviewGraphCache = new Map<string, GraphElement[]>()
const overviewGraphPending = new Map<string, Promise<GraphElement[]>>()

export function invalidateOverviewGraphCache() {
  overviewGraphCache.clear()
  overviewGraphPending.clear()
}

export async function loadOverviewGraph(
  limitPapers = 200,
  limitEdges = 600,
  options: { force?: boolean } = {},
): Promise<GraphElement[]> {
  const cacheKey = `${limitPapers}:${limitEdges}`
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
    .then((res) => {
      const nodes: GraphElement[] = (res.nodes ?? []).map((n) => ({
        group: 'nodes' as const,
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
      }))
      const edges: GraphElement[] = (res.edges ?? []).map((e) => ({
        group: 'edges' as const,
        data: {
          id: `cites:${e.source}->${e.target}`,
          source: e.source,
          target: e.target,
          kind: 'cites',
          totalMentions: e.total_mentions,
          purposeLabels: e.purpose_labels,
          weight: Math.min(1, (e.total_mentions ?? 0) / 20),
        } satisfies GraphEdgeData,
      }))
      const elements = [...nodes, ...edges]
      overviewGraphCache.set(cacheKey, elements)
      return elements
    })
    .finally(() => {
      overviewGraphPending.delete(cacheKey)
    })

  overviewGraphPending.set(cacheKey, request)
  return request
}
