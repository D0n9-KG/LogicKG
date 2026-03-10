import { beforeEach, describe, expect, test, vi } from 'vitest'

const { apiGetMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(async () => ({
    nodes: [
      {
        id: 'paper-1',
        paper_source: '14_1485',
        title: 'Process modelling in the Pharmaceutical Industry and Beyond',
        year: 2006,
        ingested: true,
        in_scope: true,
        phase1_quality_tier: 'A1',
      },
    ],
    edges: [],
  })),
}))

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
}))

import { invalidateOverviewGraphCache, loadOverviewGraph } from '../src/loaders/overview'

describe('overviewLoader', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    apiGetMock.mockImplementation(async (url: string) => {
      if (String(url).startsWith('/graph/network')) {
        return {
          nodes: [
            {
              id: 'paper-1',
              paper_source: '14_1485',
              title: 'Process modelling in the Pharmaceutical Industry and Beyond',
              year: 2006,
              ingested: true,
              in_scope: true,
              phase1_quality_tier: 'A1',
            },
          ],
          edges: [],
        }
      }
      if (String(url).startsWith('/textbooks?')) {
        return { textbooks: [] }
      }
      throw new Error(`unexpected url: ${url}`)
    })
    invalidateOverviewGraphCache()
  })

  test('preserves full paper title in description while keeping compact node label', async () => {
    const graph = await loadOverviewGraph(20, 0)
    const node = graph.find((item) => item.group === 'nodes')

    expect(node?.group).toBe('nodes')
    expect(node && node.group === 'nodes' ? node.data.label : '').toBe('14_1485')
    expect(node && node.group === 'nodes' ? node.data.description : '').toBe(
      'Process modelling in the Pharmaceutical Industry and Beyond',
    )
  })

  test('supports forcing a refresh after the cache has been primed', async () => {
    const first = await loadOverviewGraph(20, 0)

    apiGetMock.mockImplementationOnce(async () => ({
      nodes: [
        {
          id: 'paper-2',
          paper_source: '20_2000',
          title: 'Fresh overview graph',
        },
      ],
      edges: [],
    }))
    apiGetMock.mockImplementationOnce(async () => ({ textbooks: [] }))

    const cached = await loadOverviewGraph(20, 0)
    const refreshed = await loadOverviewGraph(20, 0, { force: true })

    expect(cached).toEqual(first)
    expect(refreshed.find((item) => item.group === 'nodes')?.data.id).toBe('paper-2')
    expect(apiGetMock).toHaveBeenCalledTimes(4)
  })

  test('merges textbook chapter communities into the overview graph', async () => {
    apiGetMock.mockImplementation(async (url: string) => {
      if (String(url).startsWith('/graph/network')) {
        return {
          nodes: [
            {
              id: 'paper-1',
              paper_source: '14_1485',
              title: 'Process modelling in the Pharmaceutical Industry and Beyond',
              year: 2006,
              ingested: true,
              in_scope: true,
              phase1_quality_tier: 'A1',
            },
          ],
          edges: [],
        }
      }
      if (String(url).startsWith('/textbooks?')) {
        return {
          textbooks: [{ textbook_id: 'tb:1', title: 'Continuum Mechanics', chapter_count: 1, entity_count: 2 }],
        }
      }
      if (String(url).startsWith('/textbooks/tb%3A1/graph')) {
        return {
          scope: 'textbook',
          textbook: { textbook_id: 'tb:1', title: 'Continuum Mechanics' },
          chapters: [{ chapter_id: 'tb:1:ch001', chapter_num: 1, title: 'Finite Element Foundations', entity_count: 2, relation_count: 1 }],
          entities: [
            { entity_id: 'ent-1', name: 'Finite Element Method', entity_type: 'method', source_chapter_id: 'tb:1:ch001' },
            { entity_id: 'ent-2', name: 'Galerkin Form', entity_type: 'equation', source_chapter_id: 'tb:1:ch001' },
          ],
          relations: [{ source_id: 'ent-1', target_id: 'ent-2', rel_type: 'relates_to' }],
          communities: [{ community_id: 'cluster-1', label: 'Discretization', member_ids: ['ent-1', 'ent-2'], size: 2, source: 'youtu' }],
          stats: { entity_total: 2, relation_total: 1, community_total: 1, truncated: false },
        }
      }
      throw new Error(`unexpected url: ${url}`)
    })

    const graph = await loadOverviewGraph(20, 0, { force: true })
    const nodes = graph.filter((item) => item.group === 'nodes').map((item) => item.data)
    const edges = graph.filter((item) => item.group === 'edges').map((item) => item.data)

    expect(nodes.some((node) => node.id === 'textbook:tb:1' && node.kind === 'textbook')).toBe(true)
    expect(nodes.some((node) => node.id === 'chapter:tb:1:ch001' && node.kind === 'chapter')).toBe(true)
    expect(nodes.some((node) => node.id === 'community:cluster-1' && node.kind === 'community')).toBe(true)
    expect(edges.some((edge) => edge.source === 'textbook:tb:1' && edge.target === 'chapter:tb:1:ch001' && edge.kind === 'contains')).toBe(true)
    expect(edges.some((edge) => edge.source === 'community:cluster-1' && edge.target === 'entity:ent-1' && edge.kind === 'contains')).toBe(true)
  })

  test('can load a paper-only overview graph without textbook nodes', async () => {
    apiGetMock.mockImplementation(async (url: string) => {
      if (String(url).startsWith('/graph/network')) {
        return {
          nodes: [
            {
              id: 'paper-1',
              paper_source: '14_1485',
              title: 'Paper-only graph',
              year: 2006,
              ingested: true,
              in_scope: true,
              phase1_quality_tier: 'A1',
            },
          ],
          edges: [],
        }
      }
      if (String(url).startsWith('/textbooks?')) {
        throw new Error('textbook endpoints should not be called for paper-only graph')
      }
      throw new Error(`unexpected url: ${url}`)
    })

    const graph = await loadOverviewGraph(20, 0, { force: true, includeTextbooks: false })
    const nodes = graph.filter((item) => item.group === 'nodes').map((item) => item.data)

    expect(nodes).toHaveLength(1)
    expect(nodes[0]?.kind).toBe('paper')
    expect(nodes.some((node) => node.kind === 'textbook' || node.kind === 'chapter' || node.kind === 'community')).toBe(false)
    expect(apiGetMock).toHaveBeenCalledTimes(1)
  })
})
