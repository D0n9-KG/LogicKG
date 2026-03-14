import { beforeEach, describe, expect, test, vi } from 'vitest'

const { apiGetMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
}))

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
}))

import {
  invalidateOverviewCommunity3DGraphCache,
  loadOverviewCommunity3DGraph,
} from '../src/loaders/overview'

describe('overviewCommunity3dLoader', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    invalidateOverviewCommunity3DGraphCache()
  })

  test('maps the capped community overview payload into clustered graph elements', async () => {
    apiGetMock.mockResolvedValue({
      nodes: [
        {
          id: 'community:gc:alpha',
          label: 'Alpha stability',
          kind: 'community',
          description: 'Top keywords: alpha, fem',
          cluster_key: 'community:gc:alpha',
          community_id: 'gc:alpha',
        },
        {
          id: 'claim:claim-1',
          label: 'Alpha claim with the strongest signal.',
          kind: 'claim',
          description: 'P-001 | Alpha claim with the strongest signal.',
          cluster_key: 'community:gc:alpha',
          community_id: 'gc:alpha',
          paper_id: 'paper-1',
          paper_source: 'P-001',
          paper_title: 'Alpha Study',
          step_type: 'Method',
        },
      ],
      edges: [
        {
          id: 'contains:community:gc:alpha->claim:claim-1',
          source: 'community:gc:alpha',
          target: 'claim:claim-1',
          kind: 'contains',
          weight: 0.92,
        },
      ],
      stats: {
        community_total: 1,
        visible_communities: 1,
        visible_members: 1,
        truncated: false,
      },
    })

    const graph = await loadOverviewCommunity3DGraph({
      communityLimit: 12,
      memberLimitPerCommunity: 4,
      maxNodes: 90,
      maxEdges: 140,
    })

    const nodes = graph.filter((item) => item.group === 'nodes').map((item) => item.data)
    const edges = graph.filter((item) => item.group === 'edges').map((item) => item.data)

    expect(apiGetMock).toHaveBeenCalledWith(
      '/community/overview-graph?community_limit=12&member_limit_per_community=4&max_nodes=90&max_edges=140',
    )
    expect(nodes).toEqual([
      expect.objectContaining({
        id: 'community:gc:alpha',
        kind: 'community',
        clusterKey: 'community:gc:alpha',
        communityId: 'gc:alpha',
      }),
      expect.objectContaining({
        id: 'claim:claim-1',
        kind: 'claim',
        clusterKey: 'community:gc:alpha',
        communityId: 'gc:alpha',
        paperId: 'paper-1',
        paperSource: 'P-001',
        paperTitle: 'Alpha Study',
        stepType: 'Method',
      }),
    ])
    expect(edges).toEqual([
      expect.objectContaining({
        id: 'contains:community:gc:alpha->claim:claim-1',
        source: 'community:gc:alpha',
        target: 'claim:claim-1',
        kind: 'contains',
      }),
    ])
  })
})
