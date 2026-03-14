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
})
