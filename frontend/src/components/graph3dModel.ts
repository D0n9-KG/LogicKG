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

export type SeedableGraph3DNode = FocusableNode & {
  id: string
  kind: string
  clusterKey?: string
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

function hashString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0
  }
  return Math.abs(hash)
}

function seededLocalOffset(kind: string, index: number, total: number, seed: number) {
  const angle = ((index + (seed % 17) / 17) / Math.max(total, 1)) * Math.PI * 2
  const wobble = ((seed % 29) / 29 - 0.5) * 14
  if (kind === 'textbook') return { x: 0, y: 0, z: wobble * 0.45 }
  if (kind === 'chapter') return { x: Math.cos(angle) * 70, y: Math.sin(angle) * 54, z: wobble * 0.9 }
  if (kind === 'community') return { x: Math.cos(angle) * 118, y: Math.sin(angle) * 92, z: wobble * 1.2 }
  if (kind === 'entity') return { x: Math.cos(angle) * 184, y: Math.sin(angle) * 142, z: wobble * 1.7 }
  return { x: Math.cos(angle) * 228, y: Math.sin(angle) * 164, z: wobble * 1.9 }
}

function seedCommunityOverviewCloud<T extends SeedableGraph3DNode>(nodes: T[]) {
  const goldenAngle = Math.PI * (3 - Math.sqrt(5))
  const ordered = [...nodes].sort((a, b) => a.id.localeCompare(b.id))
  const depthAmplitude = clamp(Math.round(26 + Math.sqrt(ordered.length) * 2.1), 28, 72)

  ordered.forEach((node, index) => {
    const seed = hashString(node.id)
    const radius = Math.sqrt(index + 1) * 21
    const angle = index * goldenAngle + ((seed % 19) / 19) * 0.16
    node.x = Math.cos(angle) * radius * 1.04
    node.y = Math.sin(angle) * radius * 0.78
    node.z = Math.sin(angle * 1.7) * depthAmplitude + ((seed % 23) - 11) * 1.3
  })
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

export function seedClusteredPositions<T extends SeedableGraph3DNode>(nodes: T[]) {
  const hasTextbookStructures = nodes.some((node) => node.kind === 'textbook' || node.kind === 'chapter' || node.kind === 'community')
  if (!hasTextbookStructures) return

  const isCommunityOnlyOverview = nodes.length > 0 && nodes.every((node) => node.kind === 'community')
  if (isCommunityOnlyOverview) {
    seedCommunityOverviewCloud(nodes)
    return
  }

  const groups = new Map<string, T[]>()
  const freeNodes: T[] = []
  for (const node of nodes) {
    if (!node.clusterKey) {
      freeNodes.push(node)
      continue
    }
    const bucket = groups.get(node.clusterKey) ?? []
    bucket.push(node)
    groups.set(node.clusterKey, bucket)
  }

  const clusterKeys = Array.from(groups.keys()).sort((a, b) => a.localeCompare(b))
  const clusterOrbit =
    clusterKeys.length <= 1 ? 0 : Math.max(280, Math.round(220 + Math.sqrt(clusterKeys.length) * 86))

  clusterKeys.forEach((key, clusterIndex) => {
    const members = groups.get(key) ?? []
    const angle = clusterKeys.length <= 1 ? 0 : (clusterIndex / clusterKeys.length) * Math.PI * 2
    const centerX = clusterKeys.length <= 1 ? -110 : Math.cos(angle) * clusterOrbit
    const centerY = clusterKeys.length <= 1 ? 28 : Math.sin(angle) * clusterOrbit * 0.54
    const centerZ = clusterKeys.length <= 1 ? 0 : Math.sin(angle * 1.6) * 120
    const ordered = [...members].sort((a, b) => {
      const kindRank = (kind: string) => {
        if (kind === 'textbook') return 0
        if (kind === 'chapter') return 1
        if (kind === 'community') return 2
        if (kind === 'entity') return 3
        return 4
      }
      return kindRank(a.kind) - kindRank(b.kind) || a.id.localeCompare(b.id)
    })

    ordered.forEach((node, index) => {
      const local = seededLocalOffset(node.kind, index, ordered.length, hashString(node.id))
      node.x = centerX + local.x
      node.y = centerY + local.y
      node.z = centerZ + local.z
    })
  })

  const paperNodes = freeNodes.filter((node) => node.kind === 'paper' || node.kind === 'citation')
  const outerRadius = Math.max(clusterOrbit + 220, 760)
  paperNodes.forEach((node, index) => {
    const angle = (index / Math.max(1, paperNodes.length)) * Math.PI * 2
    const seed = hashString(node.id)
    node.x = Math.cos(angle) * outerRadius
    node.y = Math.sin(angle) * outerRadius * 0.46
    node.z = ((seed % 41) - 20) * 10
  })
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
  const paddingScale = clamp(Number(options?.paddingScale) || 1.03, 1.01, 1.6)
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
