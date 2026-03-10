import { describe, expect, test } from 'vitest'

import { resolveGraphCanvasViewState } from '../src/components/graphCanvasViewState'

describe('graphCanvasViewState', () => {
  test('keeps stored overview 3D mode intact while non-overview modules render as 2D raw graphs', () => {
    const papersState = resolveGraphCanvasViewState({
      activeModule: 'papers',
      overviewMode: '3d',
      placementMode: 'timeline',
      showGraphDetails: false,
    })

    expect(papersState.show3D).toBe(false)
    expect(papersState.show2D).toBe(true)
    expect(papersState.placementMode).toBe('raw')
    expect(papersState.showGraphDetails).toBe(true)

    const overviewState = resolveGraphCanvasViewState({
      activeModule: 'overview',
      overviewMode: '3d',
      placementMode: 'timeline',
      showGraphDetails: false,
    })

    expect(overviewState.show3D).toBe(true)
    expect(overviewState.show2D).toBe(false)
    expect(overviewState.placementMode).toBe('timeline')
    expect(overviewState.showGraphDetails).toBe(false)
  })
})
