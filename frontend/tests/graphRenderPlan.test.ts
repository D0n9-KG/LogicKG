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
})
