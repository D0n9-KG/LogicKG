import cytoscape from 'cytoscape'
import { useEffect, useMemo, useRef } from 'react'

export type FusionNodeKind = 'paper' | 'textbook' | 'chapter' | 'entity' | 'logic' | 'claim'

export type FusionNode = {
  id: string
  label: string
  kind: FusionNodeKind
  score?: number
}

export type FusionEdgeKind = 'contains' | 'mentions' | 'explains' | 'supports' | 'cites'

export type FusionEdge = {
  id: string
  source: string
  target: string
  kind: FusionEdgeKind
  weight?: number
}

export type FusionGraphMode = 'macro' | 'workbench'

export type FusionGraphApi = {
  zoomIn: () => void
  zoomOut: () => void
  fit: () => void
  centerOn: (nodeId?: string) => void
}

function clampWeight(value: number | undefined) {
  const v = Number(value ?? 0)
  if (!Number.isFinite(v)) return 0
  return Math.max(0, Math.min(1, v))
}

function layoutFor(mode: FusionGraphMode): cytoscape.LayoutOptions {
  if (mode === 'macro') {
    return {
      name: 'concentric',
      animate: true,
      animationDuration: 420,
      fit: true,
      padding: 54,
      spacingFactor: 1.08,
      startAngle: (Math.PI * 3) / 2,
      sweep: Math.PI * 2,
      concentric: (node) => {
        const kind = String(node.data('kind') ?? '')
        if (kind === 'textbook') return 7
        if (kind === 'chapter') return 6
        if (kind === 'entity') return 4
        if (kind === 'paper') return 3
        if (kind === 'logic') return 2
        if (kind === 'claim') return 1
        return 0
      },
      levelWidth: () => 1,
    } as cytoscape.LayoutOptions
  }
  return {
    name: 'cose',
    animate: true,
    animationDuration: 320,
    nodeRepulsion: 250000,
    idealEdgeLength: 210,
    gravity: 0.08,
    fit: true,
    padding: 52,
  } as cytoscape.LayoutOptions
}

export default function FusionGraph({
  nodes,
  edges,
  selectedId,
  onSelect,
  mode = 'macro',
  onReady,
  height = 640,
}: {
  nodes: FusionNode[]
  edges: FusionEdge[]
  selectedId?: string
  onSelect?: (nodeId: string) => void
  mode?: FusionGraphMode
  onReady?: (api: FusionGraphApi | null) => void
  height?: number
}) {
  const ref = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)

  // Stable refs so callbacks don't re-trigger the init useEffect
  const onReadyRef = useRef(onReady)
  useEffect(() => { onReadyRef.current = onReady })
  const onSelectRef = useRef(onSelect)
  useEffect(() => { onSelectRef.current = onSelect })

  const graphData = useMemo(() => {
    const nodeIds = new Set(nodes.map((node) => node.id))
    const safeEdges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    return {
      droppedEdges: edges.length - safeEdges.length,
      elements: [
        ...nodes.map((node) => ({
          data: {
            id: node.id,
            label: node.label,
            kind: node.kind,
            score: clampWeight(node.score),
          },
        })),
        ...safeEdges.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            kind: edge.kind,
            weight: clampWeight(edge.weight),
          },
        })),
      ],
    }
  }, [edges, nodes])

  const elements = graphData.elements

  useEffect(() => {
    if (!graphData.droppedEdges) return
    console.warn(`[FusionGraph] dropped ${graphData.droppedEdges} dangling edges.`)
  }, [graphData.droppedEdges])

  useEffect(() => {
    if (!ref.current) return

    const cy = cytoscape({
      container: ref.current,
      elements,
      layout: layoutFor(mode),
      minZoom: 0.2,
      maxZoom: 2.8,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            color: 'rgba(236, 244, 255, 0.95)',
            'font-size': '12px',
            'text-wrap': 'wrap',
            'text-max-width': '180px',
            'text-background-color': 'rgba(6, 12, 24, 0.82)',
            'text-background-opacity': 1,
            'text-background-padding': '3px',
            'text-background-shape': 'roundrectangle',
            width: 'mapData(score, 0, 1, 36, 74)',
            height: 'mapData(score, 0, 1, 36, 74)',
            'background-color': 'rgba(90, 132, 255, 0.92)',
            'border-width': 1.8,
            'border-color': 'rgba(212, 229, 255, 0.84)',
            'overlay-padding': '6px',
            'overlay-opacity': 0,
          },
        },
        {
          selector: 'node[kind = "textbook"]',
          style: {
            shape: 'roundrectangle',
            width: 196,
            height: 70,
            'background-color': 'rgba(124, 255, 203, 0.88)',
            'border-color': 'rgba(190, 255, 234, 0.95)',
            color: 'rgba(8, 16, 30, 0.92)',
            'text-background-opacity': 0.34,
            'font-weight': 700,
          },
        },
        {
          selector: 'node[kind = "paper"]',
          style: {
            shape: 'roundrectangle',
            width: 220,
            height: 66,
            'background-color': 'rgba(118, 130, 255, 0.94)',
          },
        },
        {
          selector: 'node[kind = "chapter"]',
          style: {
            shape: 'roundrectangle',
            width: 168,
            height: 52,
            'background-color': 'rgba(255, 202, 132, 0.92)',
            color: 'rgba(18, 14, 8, 0.94)',
            'text-background-opacity': 0.28,
          },
        },
        {
          selector: 'node[kind = "entity"]',
          style: {
            shape: 'ellipse',
            width: 44,
            height: 44,
            'font-size': '9px',
            'text-max-width': '120px',
            'background-color': 'rgba(247, 132, 189, 0.9)',
          },
        },
        {
          selector: 'node[kind = "logic"], node[kind = "claim"]',
          style: {
            shape: 'roundrectangle',
            width: 142,
            height: 44,
            'font-size': '10px',
          },
        },
        {
          selector: 'edge',
          style: {
            width: 'mapData(weight, 0, 1, 1.4, 4.4)',
            'line-color': 'rgba(170, 202, 255, 0.52)',
            opacity: 0.88,
            'target-arrow-shape': 'triangle',
            'target-arrow-color': 'rgba(170, 202, 255, 0.68)',
            'curve-style': 'bezier',
            'arrow-scale': 0.82,
          },
        },
        {
          selector: 'edge[kind = "contains"]',
          style: {
            'line-color': 'rgba(124, 255, 203, 0.52)',
            'target-arrow-color': 'rgba(124, 255, 203, 0.56)',
          },
        },
        {
          selector: 'edge[kind = "mentions"]',
          style: {
            'line-color': 'rgba(255, 202, 132, 0.56)',
            'target-arrow-color': 'rgba(255, 202, 132, 0.56)',
          },
        },
        {
          selector: 'edge[kind = "cites"]',
          style: {
            'line-color': 'rgba(126, 139, 255, 0.52)',
            'target-arrow-color': 'rgba(126, 139, 255, 0.54)',
            'line-style': 'dashed',
          },
        },
        {
          selector: '.faded',
          style: {
            opacity: 0.14,
            'text-opacity': 0.12,
            'line-opacity': 0.12,
          },
        },
        {
          selector: '.active',
          style: {
            opacity: 1,
            'text-opacity': 1,
            'line-opacity': 1,
          },
        },
        {
          selector: '.selected',
          style: {
            'border-width': 3.4,
            'border-color': 'rgba(124, 255, 203, 1)',
          },
        },
      ],
    })

    onReadyRef.current?.({
      zoomIn: () => cy.zoom(Math.min(cy.maxZoom(), cy.zoom() * 1.15)),
      zoomOut: () => cy.zoom(Math.max(cy.minZoom(), cy.zoom() / 1.15)),
      fit: () => cy.fit(undefined, 46),
      centerOn: (nodeId) => {
        if (!nodeId) {
          cy.fit(undefined, 46)
          return
        }
        const node = cy.$id(nodeId)
        if (!node || !node.length) return
        cy.animate({ center: { eles: node } }, { duration: 220 })
      },
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
      onReadyRef.current?.(null)
      cyRef.current = null
      cy.destroy()
    }
  }, [elements, mode])

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
    cy.animate({ center: { eles: node } }, { duration: 160 })
  }, [selectedId])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.layout(layoutFor(mode)).run()
  }, [mode])

  return <div ref={ref} className="fusionGraphCanvas" style={{ height }} />
}
