import { describe, expect, test } from 'vitest'

import { resolveOverview3DPanelState } from '../src/components/overview3dLayout'

describe('overview3dLayout', () => {
  test('keeps 3D layout immersive while allowing left drawer to open', () => {
    const state = resolveOverview3DPanelState({
      activeModule: 'overview',
      overviewMode: '3d',
      hasGraphData: true,
      leftCollapsed: false,
      rightCollapsed: false,
      leftDrawerOpen: true,
      rightDrawerOpen: false,
    })

    expect(state.immersive).toBe(true)
    expect(state.layoutLeftCollapsed).toBe(true)
    expect(state.layoutRightCollapsed).toBe(true)
    expect(state.leftPanelCollapsed).toBe(false)
    expect(state.rightPanelCollapsed).toBe(true)
  })

  test('uses floating drawers for papers module without shrinking the layout', () => {
    const state = resolveOverview3DPanelState({
      activeModule: 'papers',
      overviewMode: '2d',
      hasGraphData: true,
      leftCollapsed: false,
      rightCollapsed: false,
      leftDrawerOpen: false,
      rightDrawerOpen: true,
    })

    expect(state.immersive).toBe(true)
    expect(state.layoutLeftCollapsed).toBe(true)
    expect(state.layoutRightCollapsed).toBe(true)
    expect(state.leftPanelCollapsed).toBe(true)
    expect(state.rightPanelCollapsed).toBe(false)
  })

  test('keeps ask module in the original inline sidebar layout', () => {
    const state = resolveOverview3DPanelState({
      activeModule: 'ask',
      overviewMode: '2d',
      hasGraphData: true,
      leftCollapsed: false,
      rightCollapsed: false,
      leftDrawerOpen: true,
      rightDrawerOpen: true,
    })

    expect(state.immersive).toBe(false)
    expect(state.layoutLeftCollapsed).toBe(false)
    expect(state.layoutRightCollapsed).toBe(false)
    expect(state.leftPanelCollapsed).toBe(false)
    expect(state.rightPanelCollapsed).toBe(false)
  })

  test('does not treat removed evolution module as a floating panel mode', () => {
    const state = resolveOverview3DPanelState({
      activeModule: 'evolution',
      overviewMode: '2d',
      hasGraphData: true,
      leftCollapsed: false,
      rightCollapsed: false,
      leftDrawerOpen: true,
      rightDrawerOpen: true,
    })

    expect(state.immersive).toBe(false)
    expect(state.layoutLeftCollapsed).toBe(false)
    expect(state.layoutRightCollapsed).toBe(false)
    expect(state.leftPanelCollapsed).toBe(false)
    expect(state.rightPanelCollapsed).toBe(false)
  })

  test('falls back to normal sidebar behavior outside immersive 3D mode', () => {
    const state = resolveOverview3DPanelState({
      activeModule: 'overview',
      overviewMode: '2d',
      hasGraphData: true,
      leftCollapsed: false,
      rightCollapsed: true,
      leftDrawerOpen: true,
      rightDrawerOpen: true,
    })

    expect(state.immersive).toBe(false)
    expect(state.layoutLeftCollapsed).toBe(false)
    expect(state.layoutRightCollapsed).toBe(true)
    expect(state.leftPanelCollapsed).toBe(false)
    expect(state.rightPanelCollapsed).toBe(true)
  })
})
