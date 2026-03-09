export type Graph3DViewConfig = {
  autoFitMs: number
  autoFitPadding: number
  minDistance: number
  maxDistance: number
  zoomSpeed: number
}

export type Graph3DSceneConfig = {
  fogDensity: number
}

export type GraphBounds = {
  x: [number, number]
  y: [number, number]
  z: [number, number]
}

export type FocusableNode = {
  x?: number
  y?: number
  z?: number
  val?: number
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  if (value < min) return min
  if (value > max) return max
  return value
}

function span(pair: [number, number]) {
  return Math.max(0, Number(pair[1]) - Number(pair[0]))
}

export function measureGraphBounds(bounds: GraphBounds) {
  const spanX = span(bounds.x)
  const spanY = span(bounds.y)
  const spanZ = span(bounds.z)
  const diagonal = Math.hypot(spanX, spanY, spanZ)
  return {
    center: {
      x: (Number(bounds.x[0]) + Number(bounds.x[1])) / 2,
      y: (Number(bounds.y[0]) + Number(bounds.y[1])) / 2,
      z: (Number(bounds.z[0]) + Number(bounds.z[1])) / 2,
    },
    spanX,
    spanY,
    spanZ,
    maxSpan: Math.max(spanX, spanY, spanZ),
    diagonal,
  }
}

export function buildGraph3DViewConfig(nodeCount: number, graphExtent = 0): Graph3DViewConfig {
  const size = clamp(Math.round(Number(nodeCount) || 0), 1, 2000)
  const extent = clamp(Math.round(Number(graphExtent) || 0), 0, 12000)
  return {
    autoFitMs: 420,
    autoFitPadding: clamp(Math.round(108 + Math.sqrt(size) * 2.3 + extent * 0.035), 120, 320),
    minDistance: clamp(Math.round(72 + Math.sqrt(size) * 1.1), 76, 180),
    maxDistance: clamp(Math.round(2600 + Math.sqrt(size) * 18 + extent * 6), 2800, 28000),
    zoomSpeed: 1.04,
  }
}

export function buildGraph3DSceneConfig(nodeCount: number, graphExtent = 0, cameraDistance = 0): Graph3DSceneConfig {
  const size = clamp(Math.round(Number(nodeCount) || 0), 1, 2000)
  const extent = clamp(Math.round(Number(graphExtent) || 0), 0, 12000)
  const distance = clamp(Math.round(Number(cameraDistance) || 0), 0, 40000)
  const density = 0.00036 / (1 + Math.sqrt(size / 160) + extent / 2200 + distance / 2600)
  return {
    fogDensity: clamp(density, 0.00006, 0.00018),
  }
}

export function buildFitAllCameraTarget(
  bounds: GraphBounds,
  options?: { aspect?: number; fovDeg?: number; minDistance?: number; paddingScale?: number },
): {
  position: { x: number; y: number; z: number }
  lookAt: { x: number; y: number; z: number }
  distance: number
  diagonal: number
} {
  const { center, diagonal, spanX, spanY, spanZ } = measureGraphBounds(bounds)
  const aspect = clamp(Number(options?.aspect) || 1.6, 0.5, 4)
  const fovDeg = clamp(Number(options?.fovDeg) || 40, 18, 100)
  const minDistance = clamp(Number(options?.minDistance) || 120, 48, 1200)
  const paddingScale = clamp(Number(options?.paddingScale) || 1.1, 1.02, 1.6)
  const vFov = (fovDeg * Math.PI) / 180
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * aspect)
  const fitHeightDistance = (Math.max(spanY / 2, 1) / Math.tan(vFov / 2)) * paddingScale
  const fitWidthDistance = (Math.max(spanX / 2, 1) / Math.tan(hFov / 2)) * paddingScale
  const depthOffset = Math.max(spanZ * 0.5, diagonal * 0.18, 32)
  const distance = Math.max(fitHeightDistance, fitWidthDistance, minDistance) + depthOffset

  return {
    position: { x: center.x, y: center.y, z: center.z + distance },
    lookAt: center,
    distance,
    diagonal,
  }
}

export function buildNodeFocusCameraTarget(node: FocusableNode): {
  position: { x: number; y: number; z: number }
  lookAt: { x: number; y: number; z: number }
} {
  const x = Number(node.x) || 0
  const y = Number(node.y) || 0
  const z = Number(node.z) || 0
  const radius = clamp(Number(node.val) || 6, 4, 40)
  const distance = clamp(radius * 9, 48, 180)
  return {
    position: { x, y, z: z + distance },
    lookAt: { x, y, z },
  }
}
