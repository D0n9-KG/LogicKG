// frontend/src/loaders/textbooks.ts
import { apiGet } from '../api'
import type { GraphElement, GraphNodeData, GraphEdgeData } from '../state/types'

type KnowledgeEntity = {
  entity_id: string
  name: string
  entity_type: string
  description?: string
}

type EntityRelation = {
  source_id: string
  target_id: string
  rel_type: string
}

type EntitiesResponse = {
  entities: KnowledgeEntity[]
  relations: EntityRelation[]
}

export async function loadTextbookEntityGraph(textbookId: string, chapterId?: string): Promise<GraphElement[]> {
  let url: string
  if (chapterId) {
    url = `/textbooks/${encodeURIComponent(textbookId)}/chapters/${encodeURIComponent(chapterId)}/entities?limit=300`
  } else {
    url = `/textbooks/${encodeURIComponent(textbookId)}/entities?limit=500`
  }

  const res = await apiGet<EntitiesResponse>(url)

  const nodes: GraphElement[] = (res.entities ?? []).map((e) => ({
    group: 'nodes' as const,
    data: {
      id: `entity:${e.entity_id}`,
      label: e.name,
      kind: 'entity',
      description: e.description,
      textbookId,
    } satisfies GraphNodeData,
  }))

  const edges: GraphElement[] = (res.relations ?? []).map((r) => ({
    group: 'edges' as const,
    data: {
      id: `rel:entity:${r.source_id}->entity:${r.target_id}`,
      source: `entity:${r.source_id}`,
      target: `entity:${r.target_id}`,
      kind: 'relates_to',
      weight: 0.5,
    } satisfies GraphEdgeData,
  }))

  return [...nodes, ...edges]
}
