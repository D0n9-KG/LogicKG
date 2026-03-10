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
type TextbookListResponse = {
  textbooks?: Array<{
    textbook_id?: string
    title?: string
  }>
}

const overviewGraphCache = new Map<string, GraphElement[]>()
const overviewGraphPending = new Map<string, Promise<GraphElement[]>>()
const OVERVIEW_TEXTBOOK_LIMIT = 4

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
