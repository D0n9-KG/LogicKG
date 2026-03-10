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
})
