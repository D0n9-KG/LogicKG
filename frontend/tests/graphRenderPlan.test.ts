import { describe, expect, test } from 'vitest'

import { resolveGraphRenderPlan } from '../src/components/graphRenderPlan'
import { reducer, INITIAL_STATE } from '../src/state/store'

describe('graphRenderPlan', () => {
  test('skips delayed animation when graph data is replaced during module switching', () => {
    expect(resolveGraphRenderPlan('replace')).toEqual({
      animate: false,
      animationDuration: 0,
      delayMs: 0,
      fadeBeforeSwap: false,
    })
  })

  test('keeps animated relayout for explicit relayout actions', () => {
    expect(resolveGraphRenderPlan('relayout')).toEqual({
      animate: true,
      animationDuration: 260,
      delayMs: 70,
      fadeBeforeSwap: true,
    })
  })

  test('tracks the latest graph update reason in global state', () => {
    const replaced = reducer(INITIAL_STATE, { type: 'SET_GRAPH', elements: [], layout: 'cose' })
    expect(replaced.graphUpdateReason).toBe('replace')

    const merged = reducer(replaced, { type: 'MERGE_GRAPH', elements: [] })
    expect(merged.graphUpdateReason).toBe('merge')

    const relayout = reducer(merged, { type: 'RELAYOUT' })
    expect(relayout.graphUpdateReason).toBe('relayout')
  })

  test('skips redundant graph replacement when the same graph payload is already active', () => {
    const elements = [{ group: 'nodes', data: { id: 'paper:1', label: 'Paper 1', kind: 'paper' } }] as const
    const withGraph = reducer(INITIAL_STATE, { type: 'SET_GRAPH', elements: [...elements], layout: 'cose' })
    const previousTrigger = withGraph.layoutTrigger

    const repeated = reducer(withGraph, { type: 'SET_GRAPH', elements: withGraph.graphElements, layout: 'cose' })

    expect(repeated).toBe(withGraph)
    expect(repeated.layoutTrigger).toBe(previousTrigger)
  })

  test('switching from overview to papers immediately projects the graph to paper-only elements', () => {
    const overviewGraph = [
      { group: 'nodes', data: { id: 'paper:1', label: 'Paper 1', kind: 'paper' } },
      { group: 'nodes', data: { id: 'paper:2', label: 'Paper 2', kind: 'paper' } },
      { group: 'nodes', data: { id: 'textbook:1', label: 'Textbook 1', kind: 'textbook' } },
      { group: 'edges', data: { id: 'cites:1->2', source: 'paper:1', target: 'paper:2', kind: 'cites' } },
      { group: 'edges', data: { id: 'contains:tb->p1', source: 'textbook:1', target: 'paper:1', kind: 'contains' } },
    ] as const

    const stateWithOverview = reducer(INITIAL_STATE, {
      type: 'SET_GRAPH',
      elements: [...overviewGraph],
      layout: 'cose',
    })
    const switching = reducer(stateWithOverview, { type: 'SET_TRANSITIONING', value: true })

    const switched = reducer(switching, { type: 'SET_MODULE', module: 'papers' })

    expect(switched.activeModule).toBe('papers')
    expect(switched.graphElements).toEqual([
      overviewGraph[0],
      overviewGraph[1],
      overviewGraph[3],
    ])
    expect(switched.graphUpdateReason).toBe('replace')
    expect(switched.layoutTrigger).toBe(switching.layoutTrigger + 1)
    expect(switched.transitioning).toBe(false)
  })
})
