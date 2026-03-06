import cytoscape from 'cytoscape'
import { useEffect, useMemo, useRef } from 'react'
import { type UiTheme } from '../ui/theme'

export type SignalGraphNode = {
  id: string
  label: string
  kind?:
    | 'root'
    | 'group'
    | 'textbook'
    | 'chapter'
    | 'proposition'
    | 'hotspot'
    | 'paper'
    | 'entity'
    | 'logic'
    | 'claim'
    | 'citation'
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

function clamp(value: number, min: number, max: number): number {
  if (value < min) return min
  if (value > max) return max
  return value
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

function buildPaperFlowPositions(
  nodes: SignalGraphNode[],
  edges: SignalGraphEdge[],
  viewportWidth: number,
  viewportHeight: number,
): Map<string, { x: number; y: number }> {
  const width = Math.max(840, Math.floor(viewportWidth))
  const height = Math.max(340, Math.floor(viewportHeight))
  const map = new Map<string, { x: number; y: number }>()

  const root = nodes.find((node) => node.kind === 'root') ?? nodes[0]
  const rootId = String(root?.id ?? '')

  const logicNodes = nodes
    .filter((node) => node.kind === 'logic')
    .slice()
    .sort((a, b) => parseTrailingIndex(a.id) - parseTrailingIndex(b.id))
  const claimNodes = nodes.filter((node) => node.kind === 'claim')
  const citationNodes = nodes
    .filter((node) => node.kind === 'citation')
    .slice()
    .sort((a, b) => a.label.localeCompare(b.label))
  const otherNodes = nodes.filter(
    (node) =>
      node.id !== rootId &&
      node.kind !== 'logic' &&
      node.kind !== 'claim' &&
      node.kind !== 'citation',
  )

  const yRoot = Math.round(height * 0.2)
  const yLogic = Math.round(height * 0.47)
  const yClaim = Math.round(height * 0.8)
  const citationX = Math.round(width * 0.88)
  const logicRightBound = citationNodes.length > 0 ? 0.74 : 0.9
  const logicXs = spreadLine(logicNodes.length, width * 0.1, width * logicRightBound)

  if (rootId) {
    map.set(rootId, { x: Math.round(width * 0.5), y: yRoot })
  }

  for (let i = 0; i < logicNodes.length; i += 1) {
    map.set(logicNodes[i].id, { x: Math.round(logicXs[i]), y: yLogic })
  }

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

  for (const [logicId, group] of claimsByLogic.entries()) {
    const anchor = map.get(logicId)
    const centerX = anchor?.x ?? Math.round(width * 0.42)
    const sortedGroup = group.slice().sort((a, b) => a.id.localeCompare(b.id))
    const columns = Math.min(5, Math.max(1, Math.ceil(Math.sqrt(sortedGroup.length))))
    for (let i = 0; i < sortedGroup.length; i += 1) {
      const row = Math.floor(i / columns)
      const col = i % columns
      const offsetX = (col - (columns - 1) / 2) * 58
      const offsetY = row * 38
      map.set(sortedGroup[i].id, {
        x: Math.round(clamp(centerX + offsetX, width * 0.07, width * 0.84)),
        y: Math.round(clamp(yClaim + offsetY, height * 0.68, height * 0.95)),
      })
    }
  }

  const danglingXs = spreadLine(danglingClaims.length, width * 0.09, width * 0.72)
  for (let i = 0; i < danglingClaims.length; i += 1) {
    map.set(danglingClaims[i].id, {
      x: Math.round(danglingXs[i]),
      y: Math.round(clamp(yClaim + 44, height * 0.74, height * 0.95)),
    })
  }

  const citationYs = spreadLine(citationNodes.length, height * 0.34, height * 0.86)
  for (let i = 0; i < citationNodes.length; i += 1) {
    map.set(citationNodes[i].id, { x: citationX, y: Math.round(citationYs[i]) })
  }

  const ringRadius = Math.min(width, height) * 0.2
  for (let i = 0; i < otherNodes.length; i += 1) {
    const angle = (Math.PI * 2 * i) / Math.max(1, otherNodes.length)
    map.set(otherNodes[i].id, {
      x: Math.round(width * 0.5 + ringRadius * Math.cos(angle)),
      y: Math.round(height * 0.58 + ringRadius * Math.sin(angle) * 0.55),
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
    const rootColor = isExecutive ? 'rgba(100, 187, 243, 0.9)' : 'rgba(99, 224, 255, 0.9)'
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
            label: '',
            color: 'rgba(233, 243, 255, 0.94)',
            'font-size': '9.5px',
            'text-wrap': 'ellipsis',
            'text-max-width': '130px',
            'text-background-color': isExecutive ? 'rgba(10, 18, 34, 0.92)' : 'rgba(8, 16, 31, 0.9)',
            'text-background-opacity': 1,
            'text-background-padding': '3px',
            'text-background-shape': 'roundrectangle',
            width: 'mapData(weight, 0, 1, 24, 66)',
            height: 'mapData(weight, 0, 1, 24, 66)',
            'background-color': panelNodeColor,
            'border-width': 1.7,
            'border-color': 'rgba(216, 232, 255, 0.88)',
            'overlay-opacity': 0,
          },
        },
        {
          selector: 'node[kind = "root"]',
          style: {
            label: 'data(label)',
            shape: 'roundrectangle',
            width: 216,
            height: 62,
            'font-size': '11.5px',
            'font-weight': 700,
            'background-color': rootColor,
            color: 'rgba(6, 14, 24, 0.94)',
            'text-background-opacity': 0.35,
            'text-max-width': '210px',
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
          selector: 'node[kind = "chapter"], node[kind = "paper"], node[kind = "proposition"]',
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
            label: hasPaperFlow ? '' : 'data(label)',
            shape: 'roundrectangle',
            width: hasPaperFlow ? 48 : 'mapData(weight, 0, 1, 118, 176)',
            height: hasPaperFlow ? 18 : 44,
            'background-color': isExecutive ? 'rgba(218, 164, 108, 0.9)' : 'rgba(245, 190, 127, 0.9)',
            color: 'rgba(33, 24, 12, 0.95)',
            'text-background-opacity': hasPaperFlow ? 0 : 0.34,
            'text-max-width': '156px',
            'font-size': '10px',
            'border-color': hasPaperFlow ? 'rgba(250, 220, 170, 0.92)' : 'rgba(216, 232, 255, 0.88)',
          },
        },
        {
          selector: 'node[kind = "logic"]',
          style: {
            label: 'data(label)',
            shape: 'roundrectangle',
            width: 'mapData(weight, 0, 1, 132, 190)',
            height: 46,
            'font-size': '10px',
            'font-weight': 620,
            'text-max-width': '168px',
            'background-color': isExecutive ? 'rgba(115, 205, 255, 0.9)' : 'rgba(118, 224, 255, 0.92)',
            color: 'rgba(8, 16, 26, 0.95)',
            'text-background-opacity': 0.26,
            'border-color': 'rgba(198, 242, 255, 0.86)',
          },
        },
        {
          selector: 'node[kind = "claim"]',
          style: {
            label: hasPaperFlow ? '' : 'data(label)',
            shape: 'roundrectangle',
            width: hasPaperFlow ? 40 : 'mapData(weight, 0, 1, 136, 208)',
            height: hasPaperFlow ? 18 : 48,
            'font-size': hasPaperFlow ? '9px' : '10px',
            'font-weight': 620,
            'text-max-width': '180px',
            'background-color': isExecutive ? 'rgba(210, 144, 238, 0.9)' : 'rgba(214, 152, 255, 0.92)',
            color: 'rgba(18, 10, 32, 0.94)',
            'text-background-opacity': hasPaperFlow ? 0 : 0.26,
            'border-color': 'rgba(231, 211, 255, 0.88)',
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
            'curve-style': hasPaperFlow ? 'taxi' : 'bezier',
            'taxi-direction': 'downward',
            'taxi-turn': 42,
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
            label: 'data(label)',
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
      onSelect?.(nodeId)
    })

    cy.on('tap', (evt) => {
      if (evt.target !== cy) return
      cy.elements().removeClass('faded active selected')
      onSelect?.('')
    })

    cyRef.current = cy
    return () => {
      cyRef.current = null
      cy.destroy()
    }
  }, [edges, elements, hasPaperFlow, height, nodes, onSelect, uiTheme])

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
