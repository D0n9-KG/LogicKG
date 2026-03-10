import type { OverviewMode } from './overview3dLayout'

export type GraphCanvasPlacementMode = 'raw' | 'timeline'

type GraphCanvasViewStateInput = {
  activeModule: string
  overviewMode: OverviewMode
  placementMode: GraphCanvasPlacementMode
  showGraphDetails: boolean
}

type GraphCanvasViewState = {
  show3D: boolean
  show2D: boolean
  placementMode: GraphCanvasPlacementMode
  showGraphDetails: boolean
}

export function resolveGraphCanvasViewState(input: GraphCanvasViewStateInput): GraphCanvasViewState {
  if (input.activeModule !== 'overview') {
    return {
      show3D: false,
      show2D: true,
      placementMode: 'raw',
      showGraphDetails: true,
    }
  }

  return {
    show3D: input.overviewMode === '3d',
    show2D: input.overviewMode === '2d',
    placementMode: input.placementMode,
    showGraphDetails: input.showGraphDetails,
  }
}
