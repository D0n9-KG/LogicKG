import { beforeEach, describe, expect, test, vi } from 'vitest'

const { apiGetMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
}))

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
}))

import { loadTextbookEntityGraph } from '../src/loaders/textbooks'

describe('textbook graph loader', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
  })

  test('builds a chapter graph with chapter, community, entity, and relation edges', async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/textbooks/tb-1/chapters/ch-1/graph?entity_limit=220&edge_limit=420') {
        return {
          scope: 'chapter',
          chapter: { chapter_id: 'ch-1', chapter_num: 1, title: 'Chapter 1' },
          entities: [
            { entity_id: 'e-1', name: 'Bubble', entity_type: 'concept', description: 'A bubble', source_chapter_id: 'ch-1' },
            { entity_id: 'e-2', name: 'Collapse', entity_type: 'phenomenon', description: 'A collapse', source_chapter_id: 'ch-1' },
          ],
          relations: [{ source_id: 'e-1', target_id: 'e-2', rel_type: 'causes' }],
          communities: [{ community_id: 'community:1', label: 'Cluster 1', member_ids: ['e-1', 'e-2'], size: 2, source: 'derived' }],
          stats: { entity_total: 2, relation_total: 1, community_total: 1, truncated: false },
        }
      }
      throw new Error(`Unexpected path: ${path}`)
    })

    const elements = await loadTextbookEntityGraph('tb-1', 'ch-1')

    const nodeIds = elements.filter((el) => el.group === 'nodes').map((el) => el.data.id)
    const edgeIds = elements.filter((el) => el.group === 'edges').map((el) => el.data.id)

    expect(nodeIds).toContain('chapter:ch-1')
    expect(nodeIds).toContain('community:community:1')
    expect(nodeIds).toContain('entity:e-1')
    expect(edgeIds).toContain('contains:chapter:ch-1->community:community:1')
    expect(edgeIds).toContain('contains:community:community:1->entity:e-1')
    expect(edgeIds).toContain('rel:entity:e-1->entity:e-2:causes')
  })

  test('builds a textbook overview graph with textbook root and chapter scaffolding', async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/textbooks/tb-1/graph?entity_limit=260&edge_limit=520') {
        return {
          scope: 'textbook',
          textbook: { textbook_id: 'tb-1', title: 'Textbook 1' },
          chapters: [{ chapter_id: 'ch-1', chapter_num: 1, title: 'Chapter 1', entity_count: 2, relation_count: 1 }],
          entities: [{ entity_id: 'e-1', name: 'Bubble', entity_type: 'concept', description: 'A bubble', source_chapter_id: 'ch-1' }],
          relations: [],
          communities: [{ community_id: 'community:1', label: 'Cluster 1', member_ids: ['e-1'], size: 1, source: 'derived' }],
          stats: { entity_total: 1, relation_total: 0, community_total: 1, truncated: false },
        }
      }
      throw new Error(`Unexpected path: ${path}`)
    })

    const elements = await loadTextbookEntityGraph('tb-1')

    const nodeIds = elements.filter((el) => el.group === 'nodes').map((el) => el.data.id)
    const edgeIds = elements.filter((el) => el.group === 'edges').map((el) => el.data.id)

    expect(nodeIds).toContain('textbook:tb-1')
    expect(nodeIds).toContain('chapter:ch-1')
    expect(nodeIds).toContain('community:community:1')
    expect(edgeIds).toContain('contains:textbook:tb-1->chapter:ch-1')
    expect(edgeIds).toContain('contains:chapter:ch-1->community:community:1')
  })
})
