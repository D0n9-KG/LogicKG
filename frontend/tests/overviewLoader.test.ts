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
    apiGetMock.mockResolvedValue({
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

    apiGetMock.mockResolvedValueOnce({
      nodes: [
        {
          id: 'paper-2',
          paper_source: '20_2000',
          title: 'Fresh overview graph',
        },
      ],
      edges: [],
    })

    const cached = await loadOverviewGraph(20, 0)
    const refreshed = await loadOverviewGraph(20, 0, { force: true })

    expect(cached).toEqual(first)
    expect(refreshed.find((item) => item.group === 'nodes')?.data.id).toBe('paper-2')
    expect(apiGetMock).toHaveBeenCalledTimes(2)
  })
})
