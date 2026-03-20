import { describe, expect, test } from 'vitest'

import { buildGraph3DBaseData, buildGraph3DVisibleData } from '../src/components/graph3dData'
import type { GraphElement } from '../src/state/types'

function buildOverviewCommunityElements(): GraphElement[] {
  return [
    {
      group: 'nodes',
      data: {
        id: 'community:a',
        label: 'Alpha stability',
        kind: 'community',
        keywords: ['alpha', 'stability', 'fatigue'],
        clusterKey: 'community:a',
        communityId: 'a',
      },
    },
    {
      group: 'nodes',
      data: {
        id: 'community:b',
        label: 'Beta transfer',
        kind: 'community',
        keywords: ['beta', 'transfer', 'fatigue'],
        clusterKey: 'community:b',
        communityId: 'b',
      },
    },
    {
      group: 'nodes',
      data: {
        id: 'community:c',
        label: 'Gamma diffusion',
        kind: 'community',
        keywords: ['gamma', 'diffusion'],
        clusterKey: 'community:c',
        communityId: 'c',
      },
    },
    {
      group: 'edges',
      data: {
        id: 'similar:a-b',
        source: 'community:a',
        target: 'community:b',
        kind: 'similar',
        weight: 0.92,
      },
    },
    {
      group: 'edges',
      data: {
        id: 'similar:a-c',
        source: 'community:a',
        target: 'community:c',
        kind: 'similar',
        weight: 0.61,
      },
    },
  ]
}

describe('graph3dData', () => {
  test('keeps seeded node positions stable when only the selection changes', () => {
    const baseData = buildGraph3DBaseData(buildOverviewCommunityElements())
    const initialPositions = baseData.nodes.map((node) => ({
      id: node.id,
      x: node.x,
      y: node.y,
      z: node.z,
    }))

    const unselected = buildGraph3DVisibleData(baseData, null)
    const selected = buildGraph3DVisibleData(baseData, 'community:a')

    expect(unselected.nodes).toBe(baseData.nodes)
    expect(selected.nodes).toBe(baseData.nodes)
    expect(selected.nodes).toBe(unselected.nodes)
    expect(selected.nodes.map((node) => ({ id: node.id, x: node.x, y: node.y, z: node.z }))).toEqual(initialPositions)
    expect(selected.links.map((link) => link.id)).toEqual(unselected.links.map((link) => link.id))
    expect(selected.links.map((link) => link.emphasis)).not.toEqual(unselected.links.map((link) => link.emphasis))
  })
})
