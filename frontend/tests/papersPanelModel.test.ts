import { describe, expect, test } from 'vitest'

import { derivePapersEntryGraph, shouldHydratePapersOverviewGraph } from '../src/panels/papersPanelModel'
import type { GraphElement } from '../src/state/types'

function node(id: string, kind: string): GraphElement {
  return {
    group: 'nodes',
    data: {
      id,
      label: id,
      kind,
    },
  }
}

function edge(id: string, source: string, target: string, kind: string): GraphElement {
  return {
    group: 'edges',
    data: {
      id,
      source,
      target,
      kind,
    },
  }
}

describe('papersPanelModel', () => {
  test('keeps the current graph when a paper neighborhood is already selected', () => {
    expect(shouldHydratePapersOverviewGraph([node('paper:1', 'paper'), node('logic:1', 'logic')], 'paper:1')).toBe(false)
  })

  test('reuses overview-like graphs when entering papers', () => {
    expect(
      shouldHydratePapersOverviewGraph(
        [
          node('paper:1', 'paper'),
          node('textbook:1', 'textbook'),
          node('chapter:1', 'chapter'),
          node('entity:1', 'entity'),
          node('community:1', 'community'),
        ],
        null,
      ),
    ).toBe(false)
  })

  test('requests a background refresh when the current graph comes from another workflow', () => {
    expect(shouldHydratePapersOverviewGraph([node('logic:1', 'logic'), node('paper:1', 'paper')], null)).toBe(true)
  })

  test('requests a graph when no prior nodes are available', () => {
    expect(shouldHydratePapersOverviewGraph([], null)).toBe(true)
  })

  test('derives a paper-only entry graph from overview data so papers does not flash textbook nodes', () => {
    const overviewGraph = [
      node('paper:1', 'paper'),
      node('paper:2', 'paper'),
      node('textbook:1', 'textbook'),
      node('chapter:1', 'chapter'),
      node('entity:1', 'entity'),
      node('community:1', 'community'),
      edge('cites:1', 'paper:1', 'paper:2', 'cites'),
      edge('contains:1', 'textbook:1', 'chapter:1', 'contains'),
      edge('contains:2', 'chapter:1', 'entity:1', 'contains'),
      edge('relates:1', 'entity:1', 'community:1', 'relates_to'),
    ]

    expect(derivePapersEntryGraph(overviewGraph, null)).toEqual([
      node('paper:1', 'paper'),
      node('paper:2', 'paper'),
      edge('cites:1', 'paper:1', 'paper:2', 'cites'),
    ])
  })

  test('reuses the same array when the current graph is already paper-only', () => {
    const paperGraph = [node('paper:1', 'paper'), node('paper:2', 'paper'), edge('cites:1', 'paper:1', 'paper:2', 'cites')]

    expect(derivePapersEntryGraph(paperGraph, null)).toBe(paperGraph)
  })
})
