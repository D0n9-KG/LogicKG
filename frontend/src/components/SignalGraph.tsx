/* eslint-disable react-refresh/only-export-components */
import cytoscape from 'cytoscape'
import { useEffect, useMemo, useRef } from 'react'
import { type UiTheme } from '../ui/theme'

export type SignalGraphNode = {
  id: string
  label: string
  kind?:
    | 'root'
    | 'cluster'
    | 'group'
    | 'textbook'
    | 'chapter'
    | 'hotspot'
    | 'paper'
    | 'entity'
    | 'logic'
    | 'claim'
    | 'citation'
    | 'summary'
    | 'query'
  weight?: number
}

export type SignalGraphEdge = {
  id: string
  source: string
  target: string
  kind?: string
  weight?: number
}

function clamp01(value: number | undefined) {
  const n = Number(value ?? 0)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(1, n))
}

function parseTrailingIndex(id: string): number {
  const m = String(id ?? '').match(/:(\d+)\s*$/)
  if (!m) return Number.MAX_SAFE_INTEGER
  const n = Number(m[1])
  return Number.isFinite(n) ? n : Number.MAX_SAFE_INTEGER
}

function spreadLine(count: number, start: number, end: number): number[] {
  if (count <= 0) return []
  if (count === 1) return [(start + end) / 2]
  const out: number[] = []
  for (let i = 0; i < count; i += 1) {
    out.push(start + ((end - start) * i) / (count - 1))
  }
  return out
}

const PAPER_FLOW_ROOT_RADIUS = 42
const PAPER_FLOW_LOGIC_RADIUS = 19
const PAPER_FLOW_CLAIM_RADIUS = 15
const PAPER_FLOW_FIRST_RING_RADIUS = 58
const PAPER_FLOW_RING_STEP = 46
const PAPER_FLOW_CLUSTER_PADDING = 26
const PAPER_FLOW_CLUSTER_GAP = 108
const PAPER_FLOW_ROW_GAP = 122
const PAPER_FLOW_SIDE_PADDING = 92
const PAPER_FLOW_TOP_PADDING = 126
const PAPER_FLOW_BOTTOM_PADDING = 94

function claimRingCapacity(radius: number): number {
  return Math.max(5, Math.floor((2 * Math.PI * radius) / (PAPER_FLOW_CLAIM_RADIUS * 2 + 12)))
}

function computeClusterRadius(claimCount: number): number {
  if (claimCount <= 0) return PAPER_FLOW_LOGIC_RADIUS + PAPER_FLOW_CLUSTER_PADDING + 14
  let remaining = claimCount
  let ringRadius = PAPER_FLOW_FIRST_RING_RADIUS
  while (remaining > 0) {
    const capacity = claimRingCapacity(ringRadius)
    remaining -= capacity
    if (remaining <= 0) return ringRadius + PAPER_FLOW_CLAIM_RADIUS + PAPER_FLOW_CLUSTER_PADDING
    ringRadius += PAPER_FLOW_RING_STEP
  }
  return ringRadius + PAPER_FLOW_CLAIM_RADIUS + PAPER_FLOW_CLUSTER_PADDING
}

function buildClusterSlots(
  radii: number[],
  viewportWidth: number,
  viewportHeight: number,
): {
  width: number
  height: number
  rootY: number
  contentBottomY: number
  slots: Array<{ x: number; y: number }>
} {
  const rootY = 108
  if (radii.length <= 0) {
    return {
      width: Math.max(1280, Math.floor(viewportWidth)),
      height: Math.max(940, Math.floor(viewportHeight)),
      rootY,
      contentBottomY: rootY + PAPER_FLOW_ROOT_RADIUS,
      slots: [],
    }
  }

  const columns = radii.length <= 2 ? radii.length : 2
  const rows: number[][] = []
  for (let index = 0; index < radii.length; index += columns) {
    rows.push(radii.slice(index, index + columns))
  }

  const rowWidths = rows.map((row) => row.reduce((sum, radius) => sum + radius * 2, 0) + PAPER_FLOW_CLUSTER_GAP * Math.max(0, row.length - 1))
  const widestRow = rowWidths.reduce((max, value) => Math.max(max, value), 0)
  const width = Math.max(1280, Math.floor(viewportWidth), Math.ceil(widestRow + PAPER_FLOW_SIDE_PADDING * 2))

  const slots: Array<{ x: number; y: number }> = []
  let yCursor = rootY + PAPER_FLOW_ROOT_RADIUS + PAPER_FLOW_TOP_PADDING

  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex]
    const rowRadius = row.reduce((max, radius) => Math.max(max, radius), 0)
    const rowWidth = rowWidths[rowIndex]
    const startX = (width - rowWidth) / 2
    let xCursor = startX
    const centerY = yCursor + rowRadius

    for (const radius of row) {
      slots.push({
        x: Math.round(xCursor + radius),
        y: Math.round(centerY),
      })
      xCursor += radius * 2 + PAPER_FLOW_CLUSTER_GAP
    }

    yCursor += rowRadius * 2 + PAPER_FLOW_ROW_GAP
  }

  const contentBottomY = yCursor - PAPER_FLOW_ROW_GAP
  const height = Math.max(
    940,
    Math.floor(viewportHeight),
    Math.ceil(contentBottomY + PAPER_FLOW_BOTTOM_PADDING),
  )

  return { width, height, rootY, contentBottomY, slots }
}

function claimRingStartAngle(clusterIndex: number, ringIndex: number): number {
  return (-Math.PI / 2) + (Math.PI / 9) * ((clusterIndex + ringIndex) % 6)
}

export function buildPaperFlowPositions(
  nodes: SignalGraphNode[],
  edges: SignalGraphEdge[],
  viewportWidth: number,
  viewportHeight: number,
): Map<string, { x: number; y: number }> {
  const map = new Map<string, { x: number; y: number }>()

  const root = nodes.find((node) => node.kind === 'root') ?? nodes[0]
  const rootId = String(root?.id ?? '')

  const clusterNodes = nodes.filter((node) => node.kind === 'cluster')
  const logicNodes = nodes
    .filter((node) => node.kind === 'logic')
    .slice()
    .sort((a, b) => parseTrailingIndex(a.id) - parseTrailingIndex(b.id))
  const claimNodes = nodes.filter((node) => node.kind === 'claim')
  const otherNodes = nodes.filter(
    (node) =>
      node.id !== rootId &&
      node.kind !== 'cluster' &&
      node.kind !== 'logic' &&
      node.kind !== 'claim' &&
      node.kind !== 'citation' &&
      node.kind !== 'summary',
  )

  const parentLogicByClaim = new Map<string, string>()
  for (const edge of edges) {
    const targetId = String(edge.target ?? '')
    const sourceId = String(edge.source ?? '')
    if (!targetId || !sourceId || !targetId.startsWith('claim:')) continue
    if (sourceId.startsWith('logic:')) {
      parentLogicByClaim.set(targetId, sourceId)
    }
  }

  const claimsByLogic = new Map<string, SignalGraphNode[]>()
  const danglingClaims: SignalGraphNode[] = []

  for (const claim of claimNodes) {
    const parentLogic = parentLogicByClaim.get(claim.id)
    if (!parentLogic) {
      danglingClaims.push(claim)
      continue
    }
    const group = claimsByLogic.get(parentLogic) ?? []
    group.push(claim)
    claimsByLogic.set(parentLogic, group)
  }

  const clusters = logicNodes.map((logicNode) => ({
    logicNode,
    clusterNode: clusterNodes.find((node) => node.id === logicNode.id.replace(/^logic:/, 'cluster:')),
    claims: (claimsByLogic.get(logicNode.id) ?? []).slice().sort((a, b) => a.id.localeCompare(b.id)),
    radius: computeClusterRadius((claimsByLogic.get(logicNode.id) ?? []).length),
  }))
  const layoutFrame = buildClusterSlots(
    clusters.map((cluster) => cluster.radius),
    viewportWidth,
    viewportHeight,
  )
  let width = layoutFrame.width
  let height = layoutFrame.height
  const centerX = Math.round(width * 0.5)
  const rootY = layoutFrame.rootY

  if (rootId) {
    map.set(rootId, { x: centerX, y: rootY })
  }

  for (let i = 0; i < clusters.length; i += 1) {
    const cluster = clusters[i]
    const slot = layoutFrame.slots[i] ?? { x: centerX, y: Math.round(height * 0.45) }

    map.set(cluster.logicNode.id, { x: slot.x, y: slot.y })
    if (cluster.clusterNode) {
      map.set(cluster.clusterNode.id, { x: slot.x, y: slot.y })
    }

    let placed = 0
    let ringIndex = 0
    while (placed < cluster.claims.length) {
      const ringRadius = PAPER_FLOW_FIRST_RING_RADIUS + ringIndex * PAPER_FLOW_RING_STEP
      const capacity = claimRingCapacity(ringRadius)
      const countThisRing = Math.min(capacity, cluster.claims.length - placed)
      for (let offset = 0; offset < countThisRing; offset += 1) {
        const angle =
          claimRingStartAngle(i, ringIndex) +
          (Math.PI * 2 * offset) / Math.max(1, countThisRing)
        const claimNode = cluster.claims[placed + offset]
        map.set(claimNode.id, {
          x: Math.round(slot.x + ringRadius * Math.cos(angle)),
          y: Math.round(slot.y + ringRadius * Math.sin(angle)),
        })
      }
      placed += countThisRing
      ringIndex += 1
    }
  }

  if (danglingClaims.length > 0) {
    const danglingSpan =
      danglingClaims.length * (PAPER_FLOW_CLAIM_RADIUS * 2) +
      Math.max(0, danglingClaims.length - 1) * (PAPER_FLOW_CLAIM_RADIUS * 2 + 18)
    width = Math.max(width, Math.ceil(danglingSpan + PAPER_FLOW_SIDE_PADDING * 2))
  }
  const danglingXs = spreadLine(
    danglingClaims.length,
    PAPER_FLOW_SIDE_PADDING + PAPER_FLOW_CLAIM_RADIUS,
    width - PAPER_FLOW_SIDE_PADDING - PAPER_FLOW_CLAIM_RADIUS,
  )
  const danglingY = Math.round(layoutFrame.contentBottomY + PAPER_FLOW_ROW_GAP * 0.68)
  for (let i = 0; i < danglingClaims.length; i += 1) {
    map.set(danglingClaims[i].id, {
      x: Math.round(danglingXs[i]),
      y: danglingY,
    })
  }
  if (danglingClaims.length > 0) {
    height = Math.max(height, danglingY + PAPER_FLOW_CLAIM_RADIUS + PAPER_FLOW_BOTTOM_PADDING)
  }

  const ringRadius = Math.min(width, height) * 0.16
  for (let i = 0; i < otherNodes.length; i += 1) {
    const angle = (Math.PI * 2 * i) / Math.max(1, otherNodes.length)
    map.set(otherNodes[i].id, {
      x: Math.round(centerX + ringRadius * Math.cos(angle)),
      y: Math.round((rootY + height * 0.54) / 2 + ringRadius * Math.sin(angle)),
    })
  }

  return map
}

export default function SignalGraph({
  nodes,
  edges,
  selectedId,
  uiTheme = 'research',
  onSelect,
  height = 380,
}: {
  nodes: SignalGraphNode[]
  edges: SignalGraphEdge[]
  selectedId?: string
  uiTheme?: UiTheme
  onSelect?: (nodeId: string) => void
  height?: number | string
}) {
  const ref = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const onSelectRef = useRef(onSelect)

  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  const graphData = useMemo(() => {
    const nodeIds = new Set(nodes.map((n) => n.id))
    const safeEdges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    return {
      droppedEdges: edges.length - safeEdges.length,
      elements: [
        ...nodes.map((node) => ({
          data: {
            id: node.id,
            label: node.label,
            kind: node.kind ?? 'entity',
            weight: clamp01(node.weight),
          },
        })),
        ...safeEdges.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            kind: edge.kind ?? 'link',
            weight: clamp01(edge.weight),
          },
        })),
      ],
    }
  }, [edges, nodes])

  const elements = graphData.elements
  const hasPaperFlow = useMemo(
    () => nodes.some((node) => node.kind === 'root') && nodes.some((node) => node.kind === 'logic' || node.kind === 'claim'),
    [nodes],
  )

  useEffect(() => {
    if (!graphData.droppedEdges) return
    console.warn(`[SignalGraph] dropped ${graphData.droppedEdges} dangling edges.`)
  }, [graphData.droppedEdges])

  useEffect(() => {
    if (!ref.current) return
    const isExecutive = uiTheme === 'executive'
    const panelNodeColor = isExecutive ? 'rgba(101, 154, 232, 0.92)' : 'rgba(103, 154, 244, 0.92)'
    const queryColor = isExecutive ? 'rgba(225, 170, 108, 0.92)' : 'rgba(245, 190, 127, 0.92)'
    const edgeColor = isExecutive ? 'rgba(138, 166, 210, 0.58)' : 'rgba(142, 172, 222, 0.58)'
    const selectedColor = isExecutive ? 'rgba(226, 170, 106, 1)' : 'rgba(245, 190, 127, 1)'
    const canvasHeight = typeof height === 'number' && Number.isFinite(height) ? Number(height) : 380
    const paperFlowPositions = hasPaperFlow
      ? buildPaperFlowPositions(nodes, edges, ref.current.clientWidth || 1200, canvasHeight)
      : null
    const layout = hasPaperFlow
      ? {
          name: 'preset' as const,
          fit: true,
          padding: 38,
          animate: true,
          animationDuration: 260,
          positions: (node: cytoscape.NodeSingular) => {
            return paperFlowPositions?.get(String(node.id()))
          },
        }
      : {
          name: 'cose' as const,
          animate: true,
          animationDuration: 320,
          nodeRepulsion: 260000,
          idealEdgeLength: 182,
          gravity: 0.085,
          fit: true,
          padding: 36,
        }
    const cy = cytoscape({
      container: ref.current,
      elements,
      layout,
      minZoom: 0.28,
      maxZoom: 2.8,
      style: [
        {
          selector: 'node',
          style: {
            label: hasPaperFlow ? '' : 'data(label)',
            color: 'rgba(233, 243, 255, 0.94)',
            'font-size': '8.5px',
            'text-wrap': 'wrap',
            'text-max-width': '92px',
            'text-background-color': isExecutive ? 'rgba(10, 18, 34, 0.82)' : 'rgba(8, 16, 31, 0.78)',
            'text-background-opacity': hasPaperFlow ? 0 : 0.68,
            'text-background-padding': '1px',
            'text-background-shape': 'roundrectangle',
            'text-halign': 'center',
            'text-valign': 'center',
            width: hasPaperFlow ? 'mapData(weight, 0, 1, 42, 56)' : 'mapData(weight, 0, 1, 76, 108)',
            height: hasPaperFlow ? 'mapData(weight, 0, 1, 42, 56)' : 'mapData(weight, 0, 1, 76, 108)',
            'background-color': panelNodeColor,
            'border-width': 1.8,
            'border-color': 'rgba(216, 232, 255, 0.88)',
            'overlay-opacity': 0,
          },
        },
        {
          selector: 'node[kind = "cluster"]',
          style: {
            label: '',
            shape: 'ellipse',
            width: 'mapData(weight, 0, 1, 188, 268)',
            height: 'mapData(weight, 0, 1, 188, 268)',
            'background-color': isExecutive ? 'rgba(89, 184, 196, 0.18)' : 'rgba(77, 197, 214, 0.2)',
            'background-opacity': 0.26,
            'border-color': isExecutive ? 'rgba(117, 226, 235, 0.34)' : 'rgba(117, 235, 247, 0.38)',
            'border-width': 1.4,
            'border-style': 'dashed',
            'overlay-opacity': 0,
            opacity: 0.85,
            events: 'no',
            'z-index': 1,
          },
        },
        {
          selector: 'node[kind = "root"]',
          style: {
            shape: 'ellipse',
            width: hasPaperFlow ? 84 : 150,
            height: hasPaperFlow ? 84 : 150,
            'font-size': hasPaperFlow ? '0px' : '10px',
            'font-weight': 760,
            'background-color': isExecutive ? 'rgba(60, 111, 197, 0.94)' : 'rgba(64, 108, 196, 0.94)',
            color: 'rgba(243, 248, 255, 0.98)',
            'text-background-opacity': hasPaperFlow ? 0 : 0.18,
            'text-max-width': '112px',
            'border-width': 2.4,
            'border-color': 'rgba(172, 203, 255, 0.94)',
            'z-index': 10,
          },
        },
        {
          selector: 'node[kind = "query"]',
          style: {
            label: 'data(label)',
            shape: 'roundrectangle',
            width: 206,
            height: 58,
            'font-size': '11px',
            'font-weight': 700,
            'background-color': queryColor,
            color: 'rgba(8, 14, 24, 0.95)',
            'text-background-opacity': 0.36,
          },
        },
        {
          selector: 'node[kind = "group"], node[kind = "textbook"]',
          style: {
            label: 'data(label)',
            shape: 'roundrectangle',
            width: 156,
            height: 46,
            'background-color': 'rgba(127, 143, 255, 0.92)',
          },
        },
        {
          selector: 'node[kind = "chapter"], node[kind = "paper"]',
          style: {
            label: 'data(label)',
            shape: 'roundrectangle',
            width: 'mapData(weight, 0, 1, 118, 176)',
            height: 44,
            'background-color': isExecutive ? 'rgba(218, 164, 108, 0.9)' : 'rgba(245, 190, 127, 0.9)',
            color: 'rgba(33, 24, 12, 0.95)',
            'text-background-opacity': 0.34,
            'text-max-width': '156px',
            'font-size': '10px',
          },
        },
        {
          selector: 'node[kind = "citation"]',
          style: {
            shape: 'roundrectangle',
            width: hasPaperFlow ? 'mapData(weight, 0, 1, 82, 104)' : 'mapData(weight, 0, 1, 118, 176)',
            height: hasPaperFlow ? 24 : 44,
            'background-color': isExecutive ? 'rgba(218, 164, 108, 0.9)' : 'rgba(245, 190, 127, 0.9)',
            color: 'rgba(33, 24, 12, 0.95)',
            'text-background-opacity': 0.2,
            'text-max-width': hasPaperFlow ? '78px' : '156px',
            'font-size': hasPaperFlow ? '7px' : '10px',
            'border-color': hasPaperFlow ? 'rgba(250, 220, 170, 0.92)' : 'rgba(216, 232, 255, 0.88)',
            'border-width': hasPaperFlow ? 1.4 : 1.7,
          },
        },
        {
          selector: 'node[kind = "logic"]',
          style: {
            shape: 'ellipse',
            width: hasPaperFlow ? 'mapData(weight, 0, 1, 34, 40)' : 'mapData(weight, 0, 1, 98, 118)',
            height: hasPaperFlow ? 'mapData(weight, 0, 1, 34, 40)' : 'mapData(weight, 0, 1, 98, 118)',
            'font-size': hasPaperFlow ? '0px' : '8.5px',
            'font-weight': 720,
            'text-max-width': '82px',
            'background-color': isExecutive ? 'rgba(77, 210, 220, 0.92)' : 'rgba(85, 214, 223, 0.94)',
            color: 'rgba(8, 16, 26, 0.95)',
            'text-background-opacity': hasPaperFlow ? 0 : 0.14,
            'border-color': 'rgba(182, 247, 255, 0.9)',
            'border-width': 2,
            'z-index': 11,
          },
        },
        {
          selector: 'node[kind = "claim"]',
          style: {
            shape: 'ellipse',
            width: hasPaperFlow ? 'mapData(weight, 0, 1, 30, 34)' : 'mapData(weight, 0, 1, 136, 208)',
            height: hasPaperFlow ? 'mapData(weight, 0, 1, 30, 34)' : 48,
            'font-size': hasPaperFlow ? '0px' : '10px',
            'font-weight': 620,
            'text-max-width': hasPaperFlow ? '72px' : '180px',
            'background-color': isExecutive ? 'rgba(246, 190, 106, 0.92)' : 'rgba(245, 181, 96, 0.94)',
            color: 'rgba(40, 24, 7, 0.96)',
            'text-background-opacity': hasPaperFlow ? 0 : 0.14,
            'border-color': 'rgba(255, 225, 174, 0.92)',
            'z-index': 12,
          },
        },
        {
          selector: 'node[kind = "summary"]',
          style: {
            shape: 'roundrectangle',
            width: 108,
            height: 28,
            'font-size': '7px',
            'font-weight': 700,
            'text-max-width': '92px',
            'background-color': isExecutive ? 'rgba(130, 147, 188, 0.9)' : 'rgba(122, 141, 190, 0.92)',
            color: 'rgba(241, 247, 255, 0.96)',
            'border-color': 'rgba(199, 212, 241, 0.76)',
            'text-background-opacity': 0.12,
          },
        },
        {
          selector: 'node[kind = "hotspot"]',
          style: {
            label: 'data(label)',
            shape: 'diamond',
            width: 44,
            height: 44,
            'background-color': isExecutive ? 'rgba(214, 126, 182, 0.92)' : 'rgba(236, 129, 189, 0.92)',
          },
        },
        {
          selector: 'node[kind = "entity"]',
          style: {
            shape: 'ellipse',
            width: 28,
            height: 28,
            'background-color': isExecutive ? 'rgba(88, 176, 237, 0.9)' : 'rgba(90, 206, 255, 0.9)',
          },
        },
        {
          selector: 'edge',
          style: {
            width: 'mapData(weight, 0, 1, 0.8, 2.8)',
            'line-color': edgeColor,
            opacity: hasPaperFlow ? 0.62 : 0.82,
            'target-arrow-shape': 'triangle',
            'target-arrow-color': edgeColor,
            'arrow-scale': hasPaperFlow ? 0.6 : 0.76,
            'curve-style': 'bezier',
            'line-cap': 'round',
          },
        },
        {
          selector: 'edge[kind = "contains"]',
          style: {
            'line-style': 'dashed',
            'line-dash-pattern': [7, 4],
            'line-color': isExecutive ? 'rgba(114, 190, 244, 0.7)' : 'rgba(118, 214, 255, 0.72)',
            'target-arrow-color': isExecutive ? 'rgba(114, 190, 244, 0.75)' : 'rgba(118, 214, 255, 0.78)',
          },
        },
        {
          selector: 'edge[kind = "supports"]',
          style: {
            'line-color': isExecutive ? 'rgba(147, 176, 255, 0.78)' : 'rgba(159, 185, 255, 0.8)',
            'target-arrow-color': isExecutive ? 'rgba(147, 176, 255, 0.84)' : 'rgba(159, 185, 255, 0.86)',
          },
        },
        {
          selector: 'edge[kind = "cites"]',
          style: {
            'line-style': 'dotted',
            'line-color': isExecutive ? 'rgba(255, 191, 127, 0.7)' : 'rgba(255, 206, 136, 0.72)',
            'target-arrow-color': isExecutive ? 'rgba(255, 191, 127, 0.76)' : 'rgba(255, 206, 136, 0.8)',
          },
        },
        {
          selector: 'edge[kind = "hot"]',
          style: {
            'line-color': isExecutive ? 'rgba(214, 126, 182, 0.74)' : 'rgba(236, 129, 189, 0.76)',
            'target-arrow-color': isExecutive ? 'rgba(214, 126, 182, 0.8)' : 'rgba(236, 129, 189, 0.82)',
          },
        },
        {
          selector: '.faded',
          style: {
            opacity: 0.12,
            'line-opacity': 0.12,
            'text-opacity': 0,
          },
        },
        {
          selector: '.active',
          style: {
            opacity: 1,
            'line-opacity': 1,
            'text-opacity': 1,
          },
        },
        {
          selector: '.selected',
          style: {
            'border-width': 3,
            'border-color': selectedColor,
            'background-color': isExecutive ? 'rgba(226, 170, 106, 0.94)' : 'rgba(245, 190, 127, 0.95)',
            color: 'rgba(28, 20, 9, 0.95)',
            'text-background-opacity': 1,
          },
        },
      ],
    })

    cy.on('tap', 'node', (evt) => {
      const node = evt.target
      const nodeId = String(node.data('id') ?? '')
      if (!nodeId) return
      cy.elements().addClass('faded').removeClass('active selected')
      node.closedNeighborhood().removeClass('faded').addClass('active')
      node.addClass('selected')
      onSelectRef.current?.(nodeId)
    })

    cy.on('tap', (evt) => {
      if (evt.target !== cy) return
      cy.elements().removeClass('faded active selected')
      onSelectRef.current?.('')
    })

    cyRef.current = cy
    return () => {
      cyRef.current = null
      cy.destroy()
    }
  }, [edges, elements, hasPaperFlow, height, nodes, uiTheme])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().removeClass('faded active selected')
    if (!selectedId) return
    const node = cy.$id(selectedId)
    if (!node || !node.length) return
    cy.elements().addClass('faded').removeClass('active selected')
    node.closedNeighborhood().removeClass('faded').addClass('active')
    node.addClass('selected')
    cy.animate({ center: { eles: node } }, { duration: 150 })
  }, [selectedId])

  return <div ref={ref} className="signalGraphCanvas" style={{ height }} />
}
