export type Graph3DDisplayLink = {
  id: string
  source: string
  target: string
  kind: string
  weight: number
  emphasis?: 'default' | 'background' | 'primary' | 'focus'
  visible?: boolean
  displayColor?: string
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  if (value < min) return min
  if (value > max) return max
  return value
}

function edgeTouches(link: Graph3DDisplayLink, nodeId: string) {
  return link.source === nodeId || link.target === nodeId
}

function edgeScore(link: Graph3DDisplayLink) {
  return clamp(Number(link.weight) || 0, 0, 1)
}

export function buildOverview3DVisibleLinks(
  links: Graph3DDisplayLink[],
  selectedNodeId?: string | null,
): Graph3DDisplayLink[] {
  const nonSimilar = links.filter((link) => link.kind !== 'similar').map((link) => ({ ...link, emphasis: 'default' as const }))
  const similar = links.filter((link) => link.kind === 'similar')
  if (!similar.length) return nonSimilar

  const nodeIds = new Set<string>()
  const incidentMap = new Map<string, Graph3DDisplayLink[]>()
  for (const link of similar) {
    nodeIds.add(link.source)
    nodeIds.add(link.target)
    incidentMap.set(link.source, [...(incidentMap.get(link.source) ?? []), link])
    incidentMap.set(link.target, [...(incidentMap.get(link.target) ?? []), link])
  }

  const keep = new Set<string>()
  const nodeCount = Math.max(1, nodeIds.size)
  const perNodeCap = 2
  const globalBudget = clamp(Math.round(Math.sqrt(nodeCount) * 2.5), 6, 72)
  const strongestGlobal = [...similar].sort((a, b) => edgeScore(b) - edgeScore(a)).slice(0, globalBudget)
  const primaryBudget = clamp(Math.round(Math.sqrt(nodeCount) * 1.35), 4, 18)
  const primaryIds = new Set(strongestGlobal.slice(0, primaryBudget).map((link) => link.id))
  for (const link of strongestGlobal) keep.add(link.id)

  const orderedNodeIds = Array.from(nodeIds.values()).sort((a, b) => a.localeCompare(b))
  for (const nodeId of orderedNodeIds) {
    const incident = [...(incidentMap.get(nodeId) ?? [])].sort((a, b) => edgeScore(b) - edgeScore(a))
    for (const link of incident.slice(0, perNodeCap)) keep.add(link.id)
  }

  if (selectedNodeId) {
    for (const link of incidentMap.get(selectedNodeId) ?? []) keep.add(link.id)
  }

  const visibleSimilar = similar.map((link) => {
    const isFocus = Boolean(selectedNodeId && edgeTouches(link, selectedNodeId))
    const visible = keep.has(link.id) || isFocus
    return {
      ...link,
      emphasis:
        isFocus
          ? ('focus' as const)
          : primaryIds.has(link.id)
            ? ('primary' as const)
            : ('background' as const),
      visible,
    }
  })

  return [...nonSimilar, ...visibleSimilar]
}
