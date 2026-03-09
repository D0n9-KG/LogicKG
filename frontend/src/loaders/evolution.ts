import { apiGet } from '../api'
import type { GraphElement, GraphNodeData, GraphEdgeData } from '../state/types'

type PropositionGroup = {
  group_id: string
  label_text: string
  proposition_count: number
  paper_count: number
}

type GroupDetail = {
  group_id: string
  label_text: string
  propositions: Array<{
    prop_id: string
    canonical_text: string
    current_state: string
    current_score: number
    paper_count: number
    similarity_score?: number
  }>
}

const evolutionGraphCache = new Map<number, GraphElement[]>()
const evolutionGraphPending = new Map<number, Promise<GraphElement[]>>()

export async function loadEvolutionGraph(limit = 30): Promise<GraphElement[]> {
  const cached = evolutionGraphCache.get(limit)
  if (cached) return cached

  const pending = evolutionGraphPending.get(limit)
  if (pending) return pending

  const request = apiGet<{ groups: PropositionGroup[] }>(`/evolution/groups?limit=${limit}`)
    .then((res) => {
      const groups = res.groups ?? []
      const nodes: GraphElement[] = groups.map((g) => ({
        group: 'nodes' as const,
        data: {
          id: `group:${g.group_id}`,
          label: g.label_text || g.group_id,
          kind: 'group',
          propId: g.group_id,
          degree: g.proposition_count,
        } satisfies GraphNodeData,
      }))
      evolutionGraphCache.set(limit, nodes)
      return nodes
    })
    .finally(() => {
      evolutionGraphPending.delete(limit)
    })

  evolutionGraphPending.set(limit, request)
  return request
}

export async function expandEvolutionGroup(groupId: string): Promise<GraphElement[]> {
  const res = await apiGet<GroupDetail>(`/evolution/group/${encodeURIComponent(groupId)}?limit_propositions=30`)

  const groupNodeId = `group:${res.group_id}`
  const nodes: GraphElement[] = (res.propositions ?? []).map((p) => ({
    group: 'nodes' as const,
    data: {
      id: `prop:${p.prop_id}`,
      label: p.canonical_text,
      kind: 'prop',
      state: p.current_state,
      confidence: p.current_score,
      propId: p.prop_id,
      degree: p.paper_count,
    } satisfies GraphNodeData,
  }))

  const edges: GraphElement[] = (res.propositions ?? []).map((p) => ({
    group: 'edges' as const,
    data: {
      id: `contains:${groupNodeId}->prop:${p.prop_id}`,
      source: groupNodeId,
      target: `prop:${p.prop_id}`,
      kind: 'contains',
      weight: p.similarity_score ?? 0.5,
    } satisfies GraphEdgeData,
  }))

  return [...nodes, ...edges]
}
