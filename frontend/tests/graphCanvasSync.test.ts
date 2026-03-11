import cytoscape from 'cytoscape'
import { describe, expect, test } from 'vitest'

import { syncGraphElements } from '../src/components/graphCanvasSync'

describe('graphCanvasSync', () => {
  test('removes only stale elements when replacing a graph with an overlapping subgraph', () => {
    const cy = cytoscape({
      headless: true,
      elements: [
        { group: 'nodes', data: { id: 'paper:1', label: 'Paper 1', kind: 'paper' }, position: { x: 40, y: 30 } },
        { group: 'nodes', data: { id: 'paper:2', label: 'Paper 2', kind: 'paper' }, position: { x: 120, y: 90 } },
        { group: 'nodes', data: { id: 'textbook:1', label: 'Textbook 1', kind: 'textbook' }, position: { x: 10, y: 5 } },
        { group: 'edges', data: { id: 'cites:1->2', source: 'paper:1', target: 'paper:2', kind: 'cites' } },
        { group: 'edges', data: { id: 'contains:tb->p1', source: 'textbook:1', target: 'paper:1', kind: 'contains' } },
      ],
    })

    const removedIds: string[] = []
    cy.on('remove', (event) => {
      removedIds.push(event.target.id())
    })

    syncGraphElements(cy, [
      { group: 'nodes', data: { id: 'paper:1', label: 'Paper 1 revised', kind: 'paper' }, position: { x: 320, y: 140 } },
      { group: 'nodes', data: { id: 'paper:2', label: 'Paper 2', kind: 'paper' }, position: { x: 420, y: 220 } },
      { group: 'edges', data: { id: 'cites:1->2', source: 'paper:1', target: 'paper:2', kind: 'cites' } },
    ])

    expect(removedIds.sort()).toEqual(['contains:tb->p1', 'textbook:1'])
    expect(cy.elements().map((element) => element.id()).sort()).toEqual(['cites:1->2', 'paper:1', 'paper:2'])
    expect(cy.getElementById('paper:1').data('label')).toBe('Paper 1 revised')
    expect(cy.getElementById('paper:1').position()).toMatchObject({ x: 320, y: 140 })
  })
})
