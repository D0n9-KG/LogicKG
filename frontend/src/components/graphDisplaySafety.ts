import type { GraphEdgeData, GraphElement } from '../state/types'

type LimitOptions = {
  activeModule: string
  selectedNodeId?: string | null
  maxNodes: number
  maxEdges: number
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  if (value < min) return min
  if (value > max) return max
  return value
}

function isNode(element: GraphElement): element is Extract<GraphElement, { group: 'nodes' }> {
  return element.group === 'nodes'
}

function isEdge(element: GraphElement): element is Extract<GraphElement, { group: 'edges' }> {
  return element.group === 'edges'
}

function nodeKindBoost(kind: string): number {
  if (kind === 'paper') return 0.8
  if (kind === 'community') return 0.72
  if (kind === 'logic') return 0.54
  if (kind === 'claim') return 0.5
  if (kind === 'textbook') return 0.46
  if (kind === 'chapter') return 0.42
  if (kind === 'entity') return 0.32
  if (kind === 'citation') return 0.18
  return 0.14
}

function edgeScore(edge: GraphEdgeData, degreeMap: Map<string, number>, selectedNodeId?: string | null) {
  const weight = Number(edge.weight ?? 0)
  const mentions = Number(edge.totalMentions ?? 0)
  const source = String(edge.source ?? '')
  const target = String(edge.target ?? '')
  const degreeScore = (degreeMap.get(source) ?? 0) + (degreeMap.get(target) ?? 0)
  const selectedBoost = selectedNodeId && (source === selectedNodeId || target === selectedNodeId) ? 50 : 0
  return weight * 100 + mentions * 4 + degreeScore + selectedBoost
}

export function limitGraphElementsForDisplay(elements: GraphElement[], options: LimitOptions): GraphElement[] {
  const safeMaxNodes = clamp(Math.round(options.maxNodes), 1, 1200)
  const safeMaxEdges = clamp(Math.round(options.maxEdges), 1, 2400)

  const nodes = elements.filter(isNode)
  const edges = elements.filter(isEdge)
  if (nodes.length <= safeMaxNodes && edges.length <= safeMaxEdges) {
    return elements
  }

  const degreeMap = new Map<string, number>()
  for (const edge of edges) {
    const source = String(edge.data.source ?? '')
    const target = String(edge.data.target ?? '')
    degreeMap.set(source, (degreeMap.get(source) ?? 0) + 1)
    degreeMap.set(target, (degreeMap.get(target) ?? 0) + 1)
  }

  const selectedNodeId = String(options.selectedNodeId ?? '').trim() || null
  const sortedNodes = [...nodes].sort((left, right) => {
    const leftDegree = degreeMap.get(left.data.id) ?? 0
    const rightDegree = degreeMap.get(right.data.id) ?? 0
    const leftSelected = selectedNodeId && left.data.id === selectedNodeId ? 1 : 0
    const rightSelected = selectedNodeId && right.data.id === selectedNodeId ? 1 : 0
    const leftScore = leftSelected * 1000 + leftDegree * 4 + nodeKindBoost(String(left.data.kind ?? ''))
    const rightScore = rightSelected * 1000 + rightDegree * 4 + nodeKindBoost(String(right.data.kind ?? ''))
    return rightScore - leftScore || String(left.data.label ?? '').localeCompare(String(right.data.label ?? ''))
  })

  const selectedNodeIds = new Set<string>()
  for (const node of sortedNodes.slice(0, safeMaxNodes)) {
    selectedNodeIds.add(node.data.id)
  }
  if (selectedNodeId) {
    selectedNodeIds.add(selectedNodeId)
  }

  const scoredEdges = [...edges]
    .map((edge) => edge.data)
    .filter((edge) => selectedNodeIds.has(String(edge.source ?? '')) || selectedNodeIds.has(String(edge.target ?? '')))
    .sort((left, right) => edgeScore(right, degreeMap, selectedNodeId) - edgeScore(left, degreeMap, selectedNodeId))

  for (const edge of scoredEdges) {
    if (selectedNodeIds.size >= safeMaxNodes) break
    selectedNodeIds.add(String(edge.source ?? ''))
    selectedNodeIds.add(String(edge.target ?? ''))
  }

  const limitedNodes = nodes.filter((node) => selectedNodeIds.has(node.data.id)).slice(0, safeMaxNodes)
  const limitedNodeIds = new Set(limitedNodes.map((node) => node.data.id))
  const limitedEdges = [...edges]
    .filter((edge) => limitedNodeIds.has(String(edge.data.source ?? '')) && limitedNodeIds.has(String(edge.data.target ?? '')))
    .sort((left, right) => edgeScore(right.data, degreeMap, selectedNodeId) - edgeScore(left.data, degreeMap, selectedNodeId))
    .slice(0, safeMaxEdges)

  return [...limitedNodes, ...limitedEdges]
}
