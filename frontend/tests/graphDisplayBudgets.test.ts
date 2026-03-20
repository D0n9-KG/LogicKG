import { describe, expect, test } from 'vitest'

import { getModuleDisplayBudget } from '../src/components/graphDisplayBudgets'

describe('graphDisplayBudgets', () => {
  test('uses the expanded overview and papers display budgets', () => {
    expect(getModuleDisplayBudget('overview')).toEqual({ maxNodes: 360, maxEdges: 360 })
    expect(getModuleDisplayBudget('papers')).toEqual({ maxNodes: 360, maxEdges: 360 })
    expect(getModuleDisplayBudget('textbooks')).toEqual({ maxNodes: 220, maxEdges: 180 })
    expect(getModuleDisplayBudget('ask')).toEqual({ maxNodes: 240, maxEdges: 220 })
  })

  test('widens the overview budget when a single community is expanded for inspection', () => {
    expect(getModuleDisplayBudget('overview', { expandedCommunitySubgraph: true })).toEqual({
      maxNodes: 720,
      maxEdges: 960,
    })
  })
})
