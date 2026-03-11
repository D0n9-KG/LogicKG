export type OverviewMode = '3d' | '2d'

export type Overview3DPanelStateInput = {
  activeModule: string
  overviewMode: OverviewMode
  hasGraphData: boolean
  leftCollapsed: boolean
  rightCollapsed: boolean
  leftDrawerOpen: boolean
  rightDrawerOpen: boolean
}

export type Overview3DPanelState = {
  immersive: boolean
  layoutLeftCollapsed: boolean
  layoutRightCollapsed: boolean
  leftPanelCollapsed: boolean
  rightPanelCollapsed: boolean
}

const FLOATING_PANEL_MODULES = new Set(['papers', 'textbooks'])

export function resolveOverview3DPanelState(input: Overview3DPanelStateInput): Overview3DPanelState {
  const immersive =
    input.hasGraphData &&
    ((input.activeModule === 'overview' && input.overviewMode === '3d') ||
      FLOATING_PANEL_MODULES.has(input.activeModule))

  if (!immersive) {
    return {
      immersive: false,
      layoutLeftCollapsed: input.leftCollapsed,
      layoutRightCollapsed: input.rightCollapsed,
      leftPanelCollapsed: input.leftCollapsed,
      rightPanelCollapsed: input.rightCollapsed,
    }
  }

  return {
    immersive: true,
    layoutLeftCollapsed: true,
    layoutRightCollapsed: true,
    leftPanelCollapsed: !input.leftDrawerOpen,
    rightPanelCollapsed: !input.rightDrawerOpen,
  }
}
