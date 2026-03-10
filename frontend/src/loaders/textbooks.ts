import { apiGet } from '../api'
import type { GraphEdgeData, GraphElement, GraphNodeData } from '../state/types'

type KnowledgeEntity = {
  entity_id: string
  name: string
  entity_type?: string
  description?: string
  source_chapter_id?: string
  degree?: number
  attributes?: Record<string, unknown> | string | null
}

type EntityRelation = {
  source_id: string
  target_id: string
  rel_type?: string
}

type CommunitySnapshot = {
  community_id: string
  label?: string
  member_ids?: string[]
  size?: number
  source?: string
}

type ChapterSnapshot = {
  chapter_id: string
  chapter_num?: number
  title?: string
  entity_count?: number
  relation_count?: number
}

type TextbookSnapshot = {
  textbook_id: string
  title?: string
}

type SnapshotStats = {
  entity_total?: number
  relation_total?: number
  community_total?: number
  truncated?: boolean
}

export type GraphSnapshotResponse = {
  scope?: string
  textbook?: TextbookSnapshot | null
  chapter?: ChapterSnapshot | null
  chapters?: ChapterSnapshot[]
  entities?: KnowledgeEntity[]
  relations?: EntityRelation[]
  communities?: CommunitySnapshot[]
  stats?: SnapshotStats
}

const CHAPTER_ENTITY_LIMIT = 220
const CHAPTER_EDGE_LIMIT = 420
const TEXTBOOK_ENTITY_LIMIT = 260
const TEXTBOOK_EDGE_LIMIT = 520

function textbookNodeId(textbookId: string) {
  return `textbook:${textbookId}`
}

function chapterNodeId(chapterId: string) {
  return `chapter:${chapterId}`
}

function communityNodeId(communityId: string) {
  return `community:${communityId}`
}

function entityNodeId(entityId: string) {
  return `entity:${entityId}`
}

function cleanText(value: unknown) {
  return String(value ?? '').trim()
}

function chapterLabel(chapter: ChapterSnapshot) {
  const title = cleanText(chapter.title)
  if (Number.isFinite(chapter.chapter_num)) {
    return title ? `Ch.${chapter.chapter_num} ${title}` : `Ch.${chapter.chapter_num}`
  }
  return title || cleanText(chapter.chapter_id) || 'Chapter'
}

function textbookSummary(chapterCount: number, stats?: SnapshotStats) {
  const parts = [
    `${chapterCount} chapters`,
    `${Number(stats?.entity_total ?? 0)} entities`,
    `${Number(stats?.relation_total ?? 0)} relations`,
  ]
  if (Number(stats?.community_total ?? 0) > 0) {
    parts.push(`${Number(stats?.community_total ?? 0)} communities`)
  }
  if (stats?.truncated) {
    parts.push('snapshot truncated')
  }
  return parts.join(' | ')
}

function chapterSummary(chapter: ChapterSnapshot, stats?: SnapshotStats, isFocusedChapter: boolean = false) {
  const entityCount = Number(chapter.entity_count ?? (isFocusedChapter ? stats?.entity_total : 0) ?? 0)
  const relationCount = Number(chapter.relation_count ?? (isFocusedChapter ? stats?.relation_total : 0) ?? 0)
  const parts = [`${entityCount} entities`, `${relationCount} relations`]
  if (isFocusedChapter && Number(stats?.community_total ?? 0) > 0) {
    parts.push(`${Number(stats?.community_total ?? 0)} communities`)
  }
  if (isFocusedChapter && stats?.truncated) {
    parts.push('snapshot truncated')
  }
  return parts.join(' | ')
}

function communitySummary(community: CommunitySnapshot, visibleMemberCount: number) {
  const size = Number(community.size ?? visibleMemberCount)
  const parts = [`${size} members`]
  if (visibleMemberCount > 0 && visibleMemberCount !== size) {
    parts.push(`${visibleMemberCount} visible`)
  }
  const source = cleanText(community.source)
  if (source) parts.push(source)
  return parts.join(' | ')
}

function sortChapters(a: ChapterSnapshot, b: ChapterSnapshot) {
  const numA = Number(a.chapter_num ?? Number.POSITIVE_INFINITY)
  const numB = Number(b.chapter_num ?? Number.POSITIVE_INFINITY)
  if (numA !== numB) return numA - numB
  return chapterLabel(a).localeCompare(chapterLabel(b))
}

function dedupeStrings(values: Array<string | undefined | null>) {
  return Array.from(new Set(values.map((value) => cleanText(value)).filter(Boolean)))
}

function addNode(nodeMap: Map<string, GraphElement>, data: GraphNodeData) {
  nodeMap.set(data.id, {
    group: 'nodes',
    data,
  })
}

function addEdge(edgeMap: Map<string, GraphElement>, data: GraphEdgeData) {
  edgeMap.set(data.id, {
    group: 'edges',
    data,
  })
}

export async function loadTextbookEntityGraph(textbookId: string, chapterId?: string): Promise<GraphElement[]> {
  const url = chapterId
    ? `/textbooks/${encodeURIComponent(textbookId)}/chapters/${encodeURIComponent(chapterId)}/graph?entity_limit=${CHAPTER_ENTITY_LIMIT}&edge_limit=${CHAPTER_EDGE_LIMIT}`
    : `/textbooks/${encodeURIComponent(textbookId)}/graph?entity_limit=${TEXTBOOK_ENTITY_LIMIT}&edge_limit=${TEXTBOOK_EDGE_LIMIT}`

  const snapshot = await apiGet<GraphSnapshotResponse>(url)
  return buildTextbookSnapshotGraph(snapshot, textbookId)
}

export function buildTextbookSnapshotGraph(snapshot: GraphSnapshotResponse, textbookId: string): GraphElement[] {
  const entities = snapshot.entities ?? []
  const relations = snapshot.relations ?? []
  const communities = snapshot.communities ?? []

  const nodeMap = new Map<string, GraphElement>()
  const edgeMap = new Map<string, GraphElement>()

  const textbook = snapshot.textbook && cleanText(snapshot.textbook.textbook_id)
    ? snapshot.textbook
    : { textbook_id: textbookId, title: textbookId }

  const chapterMap = new Map<string, ChapterSnapshot>()
  for (const chapter of snapshot.chapters ?? []) {
    const id = cleanText(chapter.chapter_id)
    if (!id) continue
    chapterMap.set(id, chapter)
  }
  if (snapshot.chapter && cleanText(snapshot.chapter.chapter_id)) {
    chapterMap.set(cleanText(snapshot.chapter.chapter_id), snapshot.chapter)
  }
  for (const entity of entities) {
    const sourceChapterId = cleanText(entity.source_chapter_id)
    if (!sourceChapterId || chapterMap.has(sourceChapterId)) continue
    chapterMap.set(sourceChapterId, {
      chapter_id: sourceChapterId,
      title: sourceChapterId,
    })
  }

  const chapterRows = Array.from(chapterMap.values()).sort(sortChapters)
  const textbookNode = textbook ? textbookNodeId(textbook.textbook_id) : ''
  const focusedChapterId = cleanText(snapshot.chapter?.chapter_id)

  if (textbook) {
    addNode(nodeMap, {
      id: textbookNode,
      label: cleanText(textbook.title) || cleanText(textbook.textbook_id) || 'Textbook',
      kind: 'textbook',
      description: textbookSummary(chapterRows.length, snapshot.stats),
      textbookId: cleanText(textbook.textbook_id),
      clusterKey: `textbook:${cleanText(textbook.textbook_id)}`,
    })
  }

  for (const chapter of chapterRows) {
    const id = cleanText(chapter.chapter_id)
    if (!id) continue
    addNode(nodeMap, {
      id: chapterNodeId(id),
      label: chapterLabel(chapter),
      kind: 'chapter',
      description: chapterSummary(chapter, snapshot.stats, id === focusedChapterId),
      textbookId: cleanText(textbook?.textbook_id ?? textbookId),
      chapterId: id,
      clusterKey: `textbook:${cleanText(textbook?.textbook_id ?? textbookId)}`,
    })

    if (textbookNode) {
      addEdge(edgeMap, {
        id: `contains:${textbookNode}->${chapterNodeId(id)}`,
        source: textbookNode,
        target: chapterNodeId(id),
        kind: 'contains',
        weight: 0.94,
      })
    }
  }

  const entityChapterMap = new Map<string, string>()
  for (const entity of entities) {
    const entityId = cleanText(entity.entity_id)
    if (!entityId) continue

    const sourceChapterId = cleanText(entity.source_chapter_id) || focusedChapterId
    if (sourceChapterId) entityChapterMap.set(entityId, sourceChapterId)

    const entityType = cleanText(entity.entity_type)
    const entityDetails = [entityType, cleanText(entity.description)].filter(Boolean).join(' | ')
    addNode(nodeMap, {
      id: entityNodeId(entityId),
      label: cleanText(entity.name) || entityId,
      kind: 'entity',
      description: entityDetails || undefined,
      textbookId: cleanText(textbook?.textbook_id ?? textbookId),
      chapterId: sourceChapterId || undefined,
      clusterKey: sourceChapterId ? `chapter:${sourceChapterId}` : `textbook:${cleanText(textbook?.textbook_id ?? textbookId)}`,
    })
  }

  const entityCommunityMap = new Map<string, string[]>()
  for (const community of communities) {
    const rawCommunityId = cleanText(community.community_id)
    if (!rawCommunityId) continue

    const cid = communityNodeId(rawCommunityId)
    const memberIds = dedupeStrings(community.member_ids ?? []).filter((memberId) =>
      nodeMap.has(entityNodeId(memberId)),
    )

    addNode(nodeMap, {
      id: cid,
      label: cleanText(community.label) || rawCommunityId,
      kind: 'community',
      description: communitySummary(community, memberIds.length),
      textbookId: cleanText(textbook?.textbook_id ?? textbookId),
      communityId: rawCommunityId,
      clusterKey: memberIds.length > 0 ? `community:${rawCommunityId}` : `textbook:${cleanText(textbook?.textbook_id ?? textbookId)}`,
    })

    const chapterIds = dedupeStrings(
      memberIds.map((memberId) => entityChapterMap.get(memberId) ?? focusedChapterId),
    )

    if (chapterIds.length > 0) {
      for (const sourceChapterId of chapterIds) {
        addEdge(edgeMap, {
          id: `contains:${chapterNodeId(sourceChapterId)}->${cid}`,
          source: chapterNodeId(sourceChapterId),
          target: cid,
          kind: 'contains',
          weight: 0.86,
        })
      }
    } else if (focusedChapterId) {
      addEdge(edgeMap, {
        id: `contains:${chapterNodeId(focusedChapterId)}->${cid}`,
        source: chapterNodeId(focusedChapterId),
        target: cid,
        kind: 'contains',
        weight: 0.82,
      })
    } else if (textbookNode) {
      addEdge(edgeMap, {
        id: `contains:${textbookNode}->${cid}`,
        source: textbookNode,
        target: cid,
        kind: 'contains',
        weight: 0.78,
      })
    }

    for (const memberId of memberIds) {
      const memberships = entityCommunityMap.get(memberId) ?? []
      memberships.push(cid)
      entityCommunityMap.set(memberId, memberships)
      const memberNode = nodeMap.get(entityNodeId(memberId))
      if (memberNode?.group === 'nodes') {
        memberNode.data.communityId = rawCommunityId
        memberNode.data.clusterKey = `community:${rawCommunityId}`
      }
      addEdge(edgeMap, {
        id: `contains:${cid}->${entityNodeId(memberId)}`,
        source: cid,
        target: entityNodeId(memberId),
        kind: 'contains',
        weight: 0.72,
      })
    }
  }

  for (const entity of entities) {
    const entityId = cleanText(entity.entity_id)
    if (!entityId) continue
    if ((entityCommunityMap.get(entityId) ?? []).length > 0) continue

    const sourceChapterId = entityChapterMap.get(entityId)
    if (sourceChapterId) {
      addEdge(edgeMap, {
        id: `contains:${chapterNodeId(sourceChapterId)}->${entityNodeId(entityId)}`,
        source: chapterNodeId(sourceChapterId),
        target: entityNodeId(entityId),
        kind: 'contains',
        weight: 0.64,
      })
      continue
    }

    if (textbookNode) {
      addEdge(edgeMap, {
        id: `contains:${textbookNode}->${entityNodeId(entityId)}`,
        source: textbookNode,
        target: entityNodeId(entityId),
        kind: 'contains',
        weight: 0.58,
      })
    }
  }

  for (const relation of relations) {
    const sourceId = cleanText(relation.source_id)
    const targetId = cleanText(relation.target_id)
    if (!sourceId || !targetId || sourceId === targetId) continue

    const source = entityNodeId(sourceId)
    const target = entityNodeId(targetId)
    if (!nodeMap.has(source) || !nodeMap.has(target)) continue

    const relationType = cleanText(relation.rel_type) || 'relates_to'
    addEdge(edgeMap, {
      id: `rel:${source}->${target}:${relationType}`,
      source,
      target,
      kind: 'relates_to',
      weight: 0.76,
      totalMentions: 1,
      purposeLabels: [relationType],
    })
  }

  return [...nodeMap.values(), ...edgeMap.values()]
}
