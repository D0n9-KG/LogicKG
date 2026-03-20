import { describe, expect, test } from 'vitest'

import type { GraphElement } from '../src/state/types'
import { limitGraphElementsForDisplay } from '../src/components/graphDisplaySafety'

function node(id: string): GraphElement {
  return {
    group: 'nodes',
    data: {
      id,
      label: id,
      kind: 'paper',
    },
  }
}

function edge(id: string, source: string, target: string, weight: number): GraphElement {
  return {
    group: 'edges',
    data: {
      id,
      source,
      target,
      kind: 'cites',
      weight,
    },
  }
}

describe('graphDisplaySafety', () => {
  test('keeps the selected node and strongest connected nodes when capping dense 2D graphs', () => {
    const elements: GraphElement[] = []
    for (let index = 1; index <= 14; index += 1) {
      elements.push(node(`paper:${index}`))
    }

    elements.push(edge('cites:1', 'paper:1', 'paper:2', 1))
    elements.push(edge('cites:2', 'paper:2', 'paper:3', 0.98))
    elements.push(edge('cites:3', 'paper:3', 'paper:4', 0.96))
    elements.push(edge('cites:4', 'paper:4', 'paper:5', 0.94))
    elements.push(edge('cites:5', 'paper:5', 'paper:6', 0.92))
    elements.push(edge('cites:6', 'paper:6', 'paper:7', 0.9))
    elements.push(edge('cites:selected', 'paper:14', 'paper:2', 0.12))

    const limited = limitGraphElementsForDisplay(elements, {
      activeModule: 'papers',
      selectedNodeId: 'paper:14',
      maxNodes: 6,
      maxEdges: 5,
    })

    const nodeIds = limited.filter((item) => item.group === 'nodes').map((item) => item.data.id)
    const edges = limited.filter((item) => item.group === 'edges').map((item) => item.data)

    expect(nodeIds).toHaveLength(6)
    expect(nodeIds).toContain('paper:14')
    expect(nodeIds).toContain('paper:2')
    expect(nodeIds).toContain('paper:3')
    expect(edges).toHaveLength(5)
    expect(edges.every((item) => nodeIds.includes(item.source) && nodeIds.includes(item.target))).toBe(true)
  })

  test('prefers the largest citation component over a smaller disconnected island', () => {
    const elements: GraphElement[] = [
      node('path:1'),
      node('path:2'),
      node('path:3'),
      node('path:4'),
      node('path:5'),
      node('path:6'),
      node('tri:a'),
      node('tri:b'),
      node('tri:c'),
      edge('path:e1', 'path:1', 'path:2', 1),
      edge('path:e2', 'path:2', 'path:3', 1),
      edge('path:e3', 'path:3', 'path:4', 1),
      edge('path:e4', 'path:4', 'path:5', 1),
      edge('path:e5', 'path:5', 'path:6', 1),
      edge('tri:e1', 'tri:a', 'tri:b', 1),
      edge('tri:e2', 'tri:b', 'tri:c', 1),
      edge('tri:e3', 'tri:c', 'tri:a', 1),
    ]

    const limited = limitGraphElementsForDisplay(elements, {
      activeModule: 'papers',
      maxNodes: 4,
      maxEdges: 4,
    })

    const nodeIds = limited.filter((item) => item.group === 'nodes').map((item) => item.data.id)

    expect(nodeIds).toHaveLength(4)
    expect(nodeIds.every((id) => id.startsWith('path:'))).toBe(true)
  })

  test('keeps a single largest connected component instead of mixing disconnected groups', () => {
    const elements: GraphElement[] = [
      node('alpha:a'),
      node('alpha:b'),
      node('alpha:c'),
      node('alpha:d'),
      node('alpha:e'),
      node('beta:a'),
      node('beta:b'),
      node('beta:c'),
      edge('alpha:e1', 'alpha:a', 'alpha:b', 1),
      edge('alpha:e2', 'alpha:b', 'alpha:c', 1),
      edge('alpha:e3', 'alpha:c', 'alpha:d', 1),
      edge('alpha:e4', 'alpha:d', 'alpha:e', 1),
      edge('beta:e1', 'beta:a', 'beta:b', 1),
      edge('beta:e2', 'beta:b', 'beta:c', 1),
      edge('beta:e3', 'beta:c', 'beta:a', 1),
    ]

    const limited = limitGraphElementsForDisplay(elements, {
      activeModule: 'papers',
      maxNodes: 4,
      maxEdges: 4,
    })

    const nodeIds = limited.filter((item) => item.group === 'nodes').map((item) => item.data.id)
    const edgePairs = limited
      .filter((item) => item.group === 'edges')
      .map((item) => [item.data.source, item.data.target] as const)

    expect(nodeIds).toHaveLength(4)
    expect(nodeIds.every((id) => id.startsWith('alpha:'))).toBe(true)
    expect(edgePairs.every(([source, target]) => nodeIds.includes(source) && nodeIds.includes(target))).toBe(true)
  })

  test('prefers the selected paper component even when another disconnected component is larger', () => {
    const elements: GraphElement[] = [
      node('alpha:a'),
      node('alpha:b'),
      node('alpha:c'),
      node('alpha:d'),
      node('alpha:e'),
      node('beta:a'),
      node('beta:b'),
      node('beta:c'),
      edge('alpha:e1', 'alpha:a', 'alpha:b', 1),
      edge('alpha:e2', 'alpha:b', 'alpha:c', 1),
      edge('alpha:e3', 'alpha:c', 'alpha:d', 1),
      edge('alpha:e4', 'alpha:d', 'alpha:e', 1),
      edge('beta:e1', 'beta:a', 'beta:b', 1),
      edge('beta:e2', 'beta:b', 'beta:c', 1),
      edge('beta:e3', 'beta:c', 'beta:a', 1),
    ]

    const limited = limitGraphElementsForDisplay(elements, {
      activeModule: 'papers',
      selectedNodeId: 'beta:b',
      maxNodes: 4,
      maxEdges: 4,
    })

    const nodeIds = limited.filter((item) => item.group === 'nodes').map((item) => item.data.id)

    expect(nodeIds).toContain('beta:b')
    expect(nodeIds.every((id) => id.startsWith('beta:'))).toBe(true)
    expect(nodeIds).toHaveLength(3)
  })
})
