// frontend/src/loaders/papers.ts
import { apiGet } from '../api'
import type { GraphElement, GraphNodeData, GraphEdgeData } from '../state/types'

type NeighborhoodNode = {
  id: string
  paper_source?: string
  title?: string
  doi?: string
  year?: number
  ingested?: boolean
  in_scope?: boolean
  phase1_quality_tier?: string
}

type NeighborhoodEdge = {
  source: string
  target: string
  total_mentions?: number
  purpose_labels?: string[]
}

type NeighborhoodResponse = {
  nodes: NeighborhoodNode[]
  edges: NeighborhoodEdge[]
  center_id: string
}

export async function loadPaperNeighborhood(paperId: string): Promise<GraphElement[]> {
  const qs = new URLSearchParams({ paper_id: paperId, depth: '1', limit_nodes: '80', limit_edges: '200' })
  const res = await apiGet<NeighborhoodResponse>(`/graph/neighborhood?${qs}`)

  const nodes: GraphElement[] = (res.nodes ?? []).map((n) => ({
    group: 'nodes' as const,
    data: {
      id: n.id,
      label: n.paper_source ?? n.title ?? n.doi ?? n.id,
      kind: 'paper',
      qualityTier: n.phase1_quality_tier,
      ingested: n.ingested,
      inScope: n.in_scope,
      paperId: n.id,
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
      weight: Math.min(1, (e.total_mentions ?? 0) / 20),
    } satisfies GraphEdgeData,
  }))

  return [...nodes, ...edges]
}
