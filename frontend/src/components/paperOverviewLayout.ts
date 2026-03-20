export type OverviewPoint = {
  x: number
  y: number
}

export type ComponentBox = {
  id: string
  width: number
  height: number
  weight: number
}

export type ComponentPlacement = OverviewPoint & {
  scale: number
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  if (value < min) return min
  if (value > max) return max
  return value
}

function normalizeCenteredPositions(positions: Map<string, OverviewPoint>) {
  const values = [...positions.values()]
  if (!values.length) return new Map<string, OverviewPoint>()

  const minX = Math.min(...values.map((point) => point.x))
  const maxX = Math.max(...values.map((point) => point.x))
  const minY = Math.min(...values.map((point) => point.y))
  const maxY = Math.max(...values.map((point) => point.y))
  const centerX = (minX + maxX) / 2
  const centerY = (minY + maxY) / 2

  const normalized = new Map<string, OverviewPoint>()
  for (const [id, point] of positions.entries()) {
    normalized.set(id, { x: point.x - centerX, y: point.y - centerY })
  }
  return normalized
}

function boundsOf(positions: Map<string, OverviewPoint>) {
  const values = [...positions.values()]
  if (!values.length) {
    return { width: 0, height: 0 }
  }
  const minX = Math.min(...values.map((point) => point.x))
  const maxX = Math.max(...values.map((point) => point.x))
  const minY = Math.min(...values.map((point) => point.y))
  const maxY = Math.max(...values.map((point) => point.y))
  return {
    width: Math.max(1, maxX - minX),
    height: Math.max(1, maxY - minY),
  }
}

export function orientComponentPositions(positions: Map<string, OverviewPoint>): Map<string, OverviewPoint> {
  const centered = normalizeCenteredPositions(positions)
  const { width, height } = boundsOf(centered)
  if (!centered.size || height <= width * 1.08) {
    return centered
  }

  const rotated = new Map<string, OverviewPoint>()
  for (const [id, point] of centered.entries()) {
    rotated.set(id, { x: point.y, y: -point.x })
  }
  return normalizeCenteredPositions(rotated)
}

export function placeOverviewComponents(
  boxes: ComponentBox[],
  focusId?: string | null,
): Map<string, ComponentPlacement> {
  if (!boxes.length) return new Map()

  const sorted = [...boxes].sort((left, right) => {
    const diff = right.weight - left.weight
    if (diff !== 0) return diff
    return left.id.localeCompare(right.id)
  })

  const fallbackFocusId = sorted[0]?.id ?? null
  const resolvedFocusId = sorted.some((box) => box.id === focusId) ? (focusId ?? null) : fallbackFocusId
  const focusBox = sorted.find((box) => box.id === resolvedFocusId) ?? sorted[0]
  const satellites = sorted.filter((box) => box.id !== focusBox.id)

  const placements = new Map<string, ComponentPlacement>()
  placements.set(focusBox.id, { x: 0, y: 0, scale: 1 })
  if (!satellites.length) return placements

  const maxSatelliteWeight = Math.max(...satellites.map((box) => box.weight), 1)
  const maxSatelliteWidth = Math.max(...satellites.map((box) => box.width), 1)
  const maxSatelliteHeight = Math.max(...satellites.map((box) => box.height), 1)
  const firstRingCapacity = satellites.length <= 4 ? satellites.length : 6
  const radialStepX = clamp(maxSatelliteWidth * 0.66 + 180, 260, 520)
  const radialStepY = clamp(maxSatelliteHeight * 0.56 + 140, 220, 380)
  const baseRadiusX = clamp(focusBox.width * 0.58 + maxSatelliteWidth * 0.48 + 220, 720, 1460)
  const baseRadiusY = clamp(focusBox.height * 0.46 + maxSatelliteHeight * 0.4 + 170, 540, 1180)

  for (let index = 0; index < satellites.length; index += 1) {
    const box = satellites[index]
    const ring = Math.floor(index / Math.max(firstRingCapacity, 1))
    const ringStart = ring * Math.max(firstRingCapacity, 1)
    const itemsInRing = Math.min(Math.max(firstRingCapacity, 1), satellites.length - ringStart)
    const slot = index - ringStart
    const angleStep = (Math.PI * 2) / Math.max(itemsInRing, 1)
    const angle = -Math.PI / 2 + slot * angleStep + ring * 0.32
    const radiusX = baseRadiusX + ring * radialStepX
    const radiusY = baseRadiusY + ring * radialStepY
    const normalizedWeight = clamp(box.weight / maxSatelliteWeight, 0.2, 1)
    const scale = clamp(0.58 + normalizedWeight * 0.24 - ring * 0.08, 0.52, 0.9)

    placements.set(box.id, {
      x: Math.cos(angle) * radiusX,
      y: Math.sin(angle) * radiusY,
      scale,
    })
  }

  return placements
}
