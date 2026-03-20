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

function buildAdjacency(nodes: Array<Extract<GraphElement, { group: 'nodes' }>>, edges: Array<Extract<GraphElement, { group: 'edges' }>>) {
  const adjacency = new Map<string, Set<string>>()
  for (const node of nodes) adjacency.set(node.data.id, new Set<string>())
  for (const edge of edges) {
    const source = String(edge.data.source ?? '')
    const target = String(edge.data.target ?? '')
    if (!adjacency.has(source) || !adjacency.has(target)) continue
    adjacency.get(source)?.add(target)
    adjacency.get(target)?.add(source)
  }
  return adjacency
}

function computeTwoCoreNodeIds(adjacency: Map<string, Set<string>>) {
  const degrees = new Map<string, number>()
  const removed = new Set<string>()
  const queue: string[] = []

  for (const [nodeId, neighbors] of adjacency.entries()) {
    const degree = neighbors.size
    degrees.set(nodeId, degree)
    if (degree < 2) queue.push(nodeId)
  }

  while (queue.length) {
    const nodeId = queue.shift()
    if (!nodeId || removed.has(nodeId)) continue
    removed.add(nodeId)
    for (const neighborId of adjacency.get(nodeId) ?? []) {
      if (removed.has(neighborId)) continue
      const nextDegree = Math.max(0, (degrees.get(neighborId) ?? 0) - 1)
      degrees.set(neighborId, nextDegree)
      if (nextDegree < 2) queue.push(neighborId)
    }
  }

  return new Set([...adjacency.keys()].filter((nodeId) => !removed.has(nodeId)))
}

function computeComponentIds(adjacency: Map<string, Set<string>>) {
  const componentByNode = new Map<string, string>()
  let componentIndex = 0

  for (const nodeId of adjacency.keys()) {
    if (componentByNode.has(nodeId)) continue
    componentIndex += 1
    const componentId = `component:${componentIndex}`
    const queue = [nodeId]
    componentByNode.set(nodeId, componentId)

    while (queue.length) {
      const current = queue.shift()
      if (!current) continue
      for (const neighbor of adjacency.get(current) ?? []) {
        if (componentByNode.has(neighbor)) continue
        componentByNode.set(neighbor, componentId)
        queue.push(neighbor)
      }
    }
  }

  return componentByNode
}

function nodeScore(
  nodeId: string,
  kind: string,
  degreeMap: Map<string, number>,
  coreNodeIds: Set<string>,
  selectedNodeId?: string | null,
) {
  const degree = degreeMap.get(nodeId) ?? 0
  const selectedBoost = selectedNodeId === nodeId ? 1000 : 0
  const coreBoost = coreNodeIds.has(nodeId) ? 140 : 0
  const leafPenalty = degree <= 1 && selectedNodeId !== nodeId ? -18 : 0
  return selectedBoost + coreBoost + degree * 6 + nodeKindBoost(kind) * 10 + leafPenalty
}

function compareScoredIds(leftScore: number, leftId: string, rightScore: number, rightId: string) {
  if (leftScore !== rightScore) return rightScore - leftScore
  return leftId.localeCompare(rightId)
}

function buildIncidentEdgeMap(edges: Array<Extract<GraphElement, { group: 'edges' }>>) {
  const incidentEdgeMap = new Map<string, Array<Extract<GraphElement, { group: 'edges' }>>>()
  for (const edge of edges) {
    const source = String(edge.data.source ?? '')
    const target = String(edge.data.target ?? '')
    if (!incidentEdgeMap.has(source)) incidentEdgeMap.set(source, [])
    if (!incidentEdgeMap.has(target)) incidentEdgeMap.set(target, [])
    incidentEdgeMap.get(source)?.push(edge)
    incidentEdgeMap.get(target)?.push(edge)
  }
  return incidentEdgeMap
}

export function limitGraphElementsForDisplay(elements: GraphElement[], options: LimitOptions): GraphElement[] {
  const safeMaxNodes = clamp(Math.round(options.maxNodes), 1, 1200)
  const safeMaxEdges = clamp(Math.round(options.maxEdges), 1, 2400)

  const nodes = elements.filter(isNode)
  const edges = elements.filter(isEdge)
  if (options.activeModule !== 'papers' && nodes.length <= safeMaxNodes && edges.length <= safeMaxEdges) {
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
  const adjacency = buildAdjacency(nodes, edges)
  const coreNodeIds = computeTwoCoreNodeIds(adjacency)
  const componentByNode = computeComponentIds(adjacency)

  const nodeScoreMap = new Map<string, number>()
  for (const node of nodes) {
    nodeScoreMap.set(
      node.data.id,
      nodeScore(node.data.id, String(node.data.kind ?? 'unknown'), degreeMap, coreNodeIds, selectedNodeId),
    )
  }

  const edgeScoreMap = new Map<string, number>()
  for (const edge of edges) {
    const source = String(edge.data.source ?? '')
    const target = String(edge.data.target ?? '')
    const coreBonus =
      coreNodeIds.has(source) && coreNodeIds.has(target) ? 120 : coreNodeIds.has(source) || coreNodeIds.has(target) ? 40 : 0
    const leafPenalty =
      (degreeMap.get(source) ?? 0) <= 1 && (degreeMap.get(target) ?? 0) <= 1
        ? -60
        : (degreeMap.get(source) ?? 0) <= 1 || (degreeMap.get(target) ?? 0) <= 1
          ? -24
          : 0
    edgeScoreMap.set(edge.data.id, edgeScore(edge.data, degreeMap, selectedNodeId) + coreBonus + leafPenalty)
  }

  const componentNodeMap = new Map<string, Array<Extract<GraphElement, { group: 'nodes' }>>>()
  const componentEdgeMap = new Map<string, Array<Extract<GraphElement, { group: 'edges' }>>>()
  for (const node of nodes) {
    const componentId = componentByNode.get(node.data.id) ?? `component:solo:${node.data.id}`
    if (!componentNodeMap.has(componentId)) componentNodeMap.set(componentId, [])
    componentNodeMap.get(componentId)?.push(node)
  }
  for (const edge of edges) {
    const sourceComponent = componentByNode.get(String(edge.data.source ?? ''))
    const targetComponent = componentByNode.get(String(edge.data.target ?? ''))
    if (!sourceComponent || sourceComponent !== targetComponent) continue
    if (!componentEdgeMap.has(sourceComponent)) componentEdgeMap.set(sourceComponent, [])
    componentEdgeMap.get(sourceComponent)?.push(edge)
  }

  if (options.activeModule === 'papers') {
    const targetComponentId =
      (selectedNodeId && componentByNode.get(selectedNodeId)) ??
      [...componentNodeMap.keys()].sort((left, right) => {
        const leftNodes = componentNodeMap.get(left) ?? []
        const rightNodes = componentNodeMap.get(right) ?? []
        const nodeCountDiff = rightNodes.length - leftNodes.length
        if (nodeCountDiff !== 0) return nodeCountDiff

        const edgeCountDiff = (componentEdgeMap.get(right) ?? []).length - (componentEdgeMap.get(left) ?? []).length
        if (edgeCountDiff !== 0) return edgeCountDiff

        const leftScore = leftNodes.reduce((sum, node) => sum + (nodeScoreMap.get(node.data.id) ?? 0), 0)
        const rightScore = rightNodes.reduce((sum, node) => sum + (nodeScoreMap.get(node.data.id) ?? 0), 0)
        if (leftScore !== rightScore) return rightScore - leftScore

        return left.localeCompare(right)
      })[0]

    if (!targetComponentId) return []

    const componentNodes = componentNodeMap.get(targetComponentId) ?? []
    const componentEdges = componentEdgeMap.get(targetComponentId) ?? []
    const componentNodeIds = new Set(componentNodes.map((node) => node.data.id))
    const nodeBudget = Math.min(componentNodes.length, safeMaxNodes, safeMaxEdges + 1)
    if (nodeBudget <= 0) return []

    const incidentEdgeMap = buildIncidentEdgeMap(componentEdges)
    const seedNode =
      (selectedNodeId && componentNodeIds.has(selectedNodeId)
        ? componentNodes.find((node) => node.data.id === selectedNodeId)
        : null) ??
      [...componentNodes].sort((left, right) =>
        compareScoredIds(
          nodeScoreMap.get(left.data.id) ?? 0,
          left.data.id,
          nodeScoreMap.get(right.data.id) ?? 0,
          right.data.id,
        ),
      )[0]

    if (!seedNode) return []

    const selectedNodeIds = new Set<string>([seedNode.data.id])
    const connectorEdgeIds = new Set<string>()

    while (selectedNodeIds.size < nodeBudget) {
      let bestEdge: Extract<GraphElement, { group: 'edges' }> | null = null
      let bestNeighborId: string | null = null
      let bestScore = -Infinity

      for (const nodeId of selectedNodeIds) {
        for (const edge of incidentEdgeMap.get(nodeId) ?? []) {
          const source = String(edge.data.source ?? '')
          const target = String(edge.data.target ?? '')
          const sourceSelected = selectedNodeIds.has(source)
          const targetSelected = selectedNodeIds.has(target)
          if (sourceSelected === targetSelected) continue

          const neighborId = sourceSelected ? target : source
          if (!componentNodeIds.has(neighborId)) continue

          const candidateScore = (edgeScoreMap.get(edge.data.id) ?? 0) + (nodeScoreMap.get(neighborId) ?? 0) * 2
          if (
            candidateScore > bestScore ||
            (candidateScore === bestScore &&
              bestNeighborId &&
              neighborId.localeCompare(bestNeighborId) < 0) ||
            (candidateScore === bestScore && !bestNeighborId)
          ) {
            bestEdge = edge
            bestNeighborId = neighborId
            bestScore = candidateScore
          }
        }
      }

      if (!bestEdge || !bestNeighborId) break
      selectedNodeIds.add(bestNeighborId)
      connectorEdgeIds.add(bestEdge.data.id)
    }

    const limitedNodes = componentNodes.filter((node) => selectedNodeIds.has(node.data.id))
    const selectedEdges = componentEdges.filter((edge) => {
      const source = String(edge.data.source ?? '')
      const target = String(edge.data.target ?? '')
      return selectedNodeIds.has(source) && selectedNodeIds.has(target)
    })
    const connectorEdges = selectedEdges
      .filter((edge) => connectorEdgeIds.has(edge.data.id))
      .sort((left, right) =>
        compareScoredIds(
          edgeScoreMap.get(left.data.id) ?? 0,
          left.data.id,
          edgeScoreMap.get(right.data.id) ?? 0,
          right.data.id,
        ),
      )
    const extraEdges = selectedEdges
      .filter((edge) => !connectorEdgeIds.has(edge.data.id))
      .sort((left, right) =>
        compareScoredIds(
          edgeScoreMap.get(left.data.id) ?? 0,
          left.data.id,
          edgeScoreMap.get(right.data.id) ?? 0,
          right.data.id,
        ),
      )
    const limitedEdges = [...connectorEdges, ...extraEdges].slice(0, safeMaxEdges)

    return [...limitedNodes, ...limitedEdges]
  }

  const rankedComponentIds = [...componentNodeMap.keys()].sort((left, right) => {
    const leftNodeScore = (componentNodeMap.get(left) ?? [])
      .map((node) => nodeScoreMap.get(node.data.id) ?? 0)
      .sort((a, b) => b - a)
      .slice(0, 3)
      .reduce((sum, score) => sum + score, 0)
    const rightNodeScore = (componentNodeMap.get(right) ?? [])
      .map((node) => nodeScoreMap.get(node.data.id) ?? 0)
      .sort((a, b) => b - a)
      .slice(0, 3)
      .reduce((sum, score) => sum + score, 0)
    const leftEdgeScore = (componentEdgeMap.get(left) ?? [])
      .map((edge) => edgeScoreMap.get(edge.data.id) ?? 0)
      .sort((a, b) => b - a)
      .slice(0, 3)
      .reduce((sum, score) => sum + score, 0)
    const rightEdgeScore = (componentEdgeMap.get(right) ?? [])
      .map((edge) => edgeScoreMap.get(edge.data.id) ?? 0)
      .sort((a, b) => b - a)
      .slice(0, 3)
      .reduce((sum, score) => sum + score, 0)
    const diff = rightNodeScore + rightEdgeScore - (leftNodeScore + leftEdgeScore)
    if (diff !== 0) return diff
    return left.localeCompare(right)
  })

  const selectedNodeIds = new Set<string>()
  if (selectedNodeId) {
    selectedNodeIds.add(selectedNodeId)
    const selectedIncidentEdges = [...edges]
      .filter((edge) => String(edge.data.source ?? '') === selectedNodeId || String(edge.data.target ?? '') === selectedNodeId)
      .sort((left, right) => (edgeScoreMap.get(right.data.id) ?? 0) - (edgeScoreMap.get(left.data.id) ?? 0))
    for (const edge of selectedIncidentEdges) {
      if (selectedNodeIds.size >= safeMaxNodes) break
      const source = String(edge.data.source ?? '')
      const target = String(edge.data.target ?? '')
      const neighborId = source === selectedNodeId ? target : source
      if (neighborId) selectedNodeIds.add(neighborId)
    }

    const neighborhoodTarget = Math.min(safeMaxNodes, 4)
    const expansionEdges = [...edges].sort((left, right) => (edgeScoreMap.get(right.data.id) ?? 0) - (edgeScoreMap.get(left.data.id) ?? 0))
    let expanded = true
    while (selectedNodeIds.size < neighborhoodTarget && expanded) {
      expanded = false
      for (const edge of expansionEdges) {
        const source = String(edge.data.source ?? '')
        const target = String(edge.data.target ?? '')
        const sourceSelected = selectedNodeIds.has(source)
        const targetSelected = selectedNodeIds.has(target)
        if (sourceSelected === targetSelected) continue
        selectedNodeIds.add(source)
        selectedNodeIds.add(target)
        expanded = true
        if (selectedNodeIds.size >= neighborhoodTarget) break
      }
    }
  }

  const componentBonusMap = new Map<string, number>()
  for (const componentId of rankedComponentIds) {
    const componentNodes = componentNodeMap.get(componentId) ?? []
    const componentEdges = componentEdgeMap.get(componentId) ?? []
    const coreCount = componentNodes.filter((node) => coreNodeIds.has(node.data.id)).length
    componentBonusMap.set(componentId, coreCount * 40 + componentEdges.length * 2)
  }
  const selectedComponentId = selectedNodeId ? componentByNode.get(selectedNodeId) ?? null : null

  const edgeIdsByNode = new Map<string, string[]>()
  for (const edge of edges) {
    const source = String(edge.data.source ?? '')
    const target = String(edge.data.target ?? '')
    if (!edgeIdsByNode.has(source)) edgeIdsByNode.set(source, [])
    if (!edgeIdsByNode.has(target)) edgeIdsByNode.set(target, [])
    edgeIdsByNode.get(source)?.push(edge.data.id)
    edgeIdsByNode.get(target)?.push(edge.data.id)
  }

  while (selectedNodeIds.size < safeMaxNodes) {
    let bestNode: Extract<GraphElement, { group: 'nodes' }> | null = null
    let bestScore = -Infinity

    for (const node of nodes) {
      if (selectedNodeIds.has(node.data.id)) continue
      const componentId = componentByNode.get(node.data.id) ?? ''
      const selectedCountInComponent = (componentNodeMap.get(componentId) ?? []).filter((row) => selectedNodeIds.has(row.data.id)).length
      const preferredCount = selectedComponentId && componentId === selectedComponentId ? Math.min(6, safeMaxNodes) : 0
      const componentPenalty = Math.max(0, selectedCountInComponent - preferredCount) * 60
      const adjacencyBoost = Math.max(
        0,
        ...((edgeIdsByNode.get(node.data.id) ?? []).map((edgeId) => {
          const edge = edges.find((row) => row.data.id === edgeId)
          if (!edge) return 0
          const source = String(edge.data.source ?? '')
          const target = String(edge.data.target ?? '')
          if (!selectedNodeIds.has(source) && !selectedNodeIds.has(target)) return 0
          return Math.round((edgeScoreMap.get(edgeId) ?? 0) * 0.22)
        })),
      )
      const candidateScore =
        (nodeScoreMap.get(node.data.id) ?? 0) +
        (componentBonusMap.get(componentId) ?? 0) -
        componentPenalty +
        adjacencyBoost
      const label = String(node.data.label ?? '')
      const bestLabel = String(bestNode?.data.label ?? '')
      if (candidateScore > bestScore || (candidateScore === bestScore && label.localeCompare(bestLabel) < 0)) {
        bestNode = node
        bestScore = candidateScore
      }
    }

    if (!bestNode) break
    selectedNodeIds.add(bestNode.data.id)
  }

  const limitedNodes = nodes.filter((node) => selectedNodeIds.has(node.data.id)).slice(0, safeMaxNodes)
  const limitedNodeIds = new Set(limitedNodes.map((node) => node.data.id))
  const limitedEdges = [...edges]
    .filter((edge) => limitedNodeIds.has(String(edge.data.source ?? '')) && limitedNodeIds.has(String(edge.data.target ?? '')))
    .sort((left, right) => (edgeScoreMap.get(right.data.id) ?? 0) - (edgeScoreMap.get(left.data.id) ?? 0))
    .slice(0, safeMaxEdges)

  return [...limitedNodes, ...limitedEdges]
}
