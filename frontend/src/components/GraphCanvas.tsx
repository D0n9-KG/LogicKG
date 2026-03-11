import cytoscape from 'cytoscape'
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n, type UILocale } from '../i18n'
import { paperRefForAskScope } from '../paperRefs'
import type { GraphEdgeData, GraphElement, GraphNodeData, LayoutName, SelectedNode } from '../state/types'
import { loadScope, saveScope } from '../scope'
import { useGlobalState } from '../state/store'
import { syncGraphElements } from './graphCanvasSync'
import { resolveGraphCanvasViewState } from './graphCanvasViewState'
import { resolveGraphRenderPlan } from './graphRenderPlan'

const Graph3D = lazy(() => import('./Graph3D'))

type Props = {
  elements: GraphElement[]
  layout: LayoutName
  layoutTrigger: number
  overviewMode: '3d' | '2d'
  onOverviewModeChange: (mode: '3d' | '2d') => void
  transitioning: boolean
  onSelectNode: (node: SelectedNode | null) => void
}

type NodeVisual = {
  color: string
  borderColor: string
  shape: string
  size: number
}

type EdgeVisual = {
  color: string
  lineStyle: 'solid' | 'dashed'
  arrow: 'none' | 'triangle'
  width: number
  opacity: number
}

type PlacementMode = 'raw' | 'timeline'

type InternalEdge = GraphEdgeData & {
  aggregateCount?: number
}

type MiniMapSnapshot = {
  nodes: Array<{ x: number; y: number; color: string; size: number }>
  bounds: { x1: number; y1: number; w: number; h: number }
  viewport: { x: number; y: number; w: number; h: number }
}

type PositionedElement = {
  group: 'nodes' | 'edges'
  data: Record<string, unknown>
  position?: { x: number; y: number }
}

type LayoutMeta = {
  yearAnchors: Array<{ key: string; label: string }>
  yearAxis: Array<{ key: string; label: string; x: number }>
  laneSummary: string[]
}

type PreparedGraph = {
  elements: PositionedElement[]
  rawEdgeCount: number
  renderedEdgeCount: number
  layoutMeta: LayoutMeta
}

type PositionedNode = {
  x: number
  y: number
  anchorX: number
  anchorY: number
}

type TimelineViewport = {
  start: number
  end: number
  startLabel: string
  endLabel: string
}

type LocalizedText = {
  zh: string
  en: string
}

function pickText(locale: UILocale, text: LocalizedText): string {
  return locale === 'zh-CN' ? text.zh : text.en
}

const KIND_LABELS: Record<string, LocalizedText> = {
  textbook: { zh: '\u6559\u6750', en: 'Textbook' },
  chapter: { zh: '\u7ae0\u8282', en: 'Chapter' },
  community: { zh: '\u793e\u533a', en: 'Community' },
  paper: { zh: '论文', en: 'Paper' },
  logic: { zh: '逻辑', en: 'Logic' },
  claim: { zh: '论断', en: 'Claim' },
  prop: { zh: '命题', en: 'Proposition' },
  proposition: { zh: '命题', en: 'Proposition' },
  group: { zh: '分组', en: 'Group' },
  entity: { zh: '实体', en: 'Entity' },
  citation: { zh: '引文', en: 'Citation' },
}

const KIND_PRIORITY: Record<string, number> = {
  textbook: 1,
  chapter: 2,
  community: 3,
  paper: 4,
  logic: 5,
  claim: 6,
  prop: 7,
  proposition: 7,
  group: 8,
  entity: 9,
  citation: 10,
}

const PLACEMENT_MODE_LABELS: Record<PlacementMode, LocalizedText> = {
  raw: { zh: '原始', en: 'Raw Mesh' },
  timeline: { zh: '时间线', en: 'Timeline' },
}

const YEAR_GAP = 230
const LANE_GAP = 220
const SPIRAL_STEP = 18
const MIN_NODE_DISTANCE = 28
const RELAX_ROUNDS = 3
const EDGE_SPRING_IN_BUCKET = 76
const EDGE_SPRING_CROSS_BUCKET = 122
const EDGE_SPRING_K = 0.004
const ANCHOR_PULL = 0.17

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  if (value < min) return min
  if (value > max) return max
  return value
}

function shortLabel(label: string, max = 28): string {
  const text = String(label ?? '').replace(/\s+/g, ' ').trim()
  if (!text || text.length <= max) return text
  return `${text.slice(0, Math.max(1, max - 3))}...`
}

function nearestAxisLabel(x: number, axis: Array<{ label: string; x: number }>): string {
  if (!axis.length) return '--'
  let best = axis[0]
  let bestDist = Math.abs(x - best.x)
  for (let i = 1; i < axis.length; i += 1) {
    const item = axis[i]
    const dist = Math.abs(x - item.x)
    if (dist < bestDist) {
      best = item
      bestDist = dist
    }
  }
  return best.label
}

function validYear(value: unknown): number | null {
  const year = Number(value ?? 0)
  if (!Number.isFinite(year)) return null
  if (year < 1900 || year > 2100) return null
  return Math.round(year)
}

function kindLabel(kind: string, locale: UILocale) {
  const key = String(kind ?? '')
  const text = KIND_LABELS[key]
  return text ? pickText(locale, text) : key || 'other'
}

function kindOrder(kind: string) {
  return KIND_PRIORITY[String(kind ?? '')] ?? 99
}

function nodeVisual(data: GraphNodeData, degree: number): NodeVisual {
  const weightedDegree = clamp(Math.round(degree), 0, 24)
  if (data.kind === 'textbook') {
    return {
      color: 'rgba(34, 211, 238, 0.94)',
      borderColor: 'rgba(207, 250, 254, 0.96)',
      shape: 'round-rectangle',
      size: 24 + Math.min(30, weightedDegree * 1.15),
    }
  }
  if (data.kind === 'chapter') {
    return {
      color: 'rgba(251, 191, 36, 0.92)',
      borderColor: 'rgba(254, 243, 199, 0.94)',
      shape: 'hexagon',
      size: 20 + Math.min(22, weightedDegree * 0.9),
    }
  }
  if (data.kind === 'community') {
    return {
      color: 'rgba(45, 212, 191, 0.92)',
      borderColor: 'rgba(204, 251, 241, 0.92)',
      shape: 'round-rectangle',
      size: 18 + Math.min(22, weightedDegree * 0.9),
    }
  }
  if (data.kind === 'paper') {
    const imported = data.ingested !== false
    if (!imported) {
      return {
        color: 'rgba(125, 211, 252, 0.42)',
        borderColor: 'rgba(148, 163, 184, 0.46)',
        shape: 'ellipse',
        size: 13 + Math.min(16, weightedDegree * 0.65),
      }
    }
    const tier = String(data.qualityTier ?? '')
    const color =
      tier === 'A1'
        ? 'rgba(125, 211, 252, 0.99)'
        : tier === 'A2'
          ? 'rgba(56, 189, 248, 0.98)'
          : tier === 'B1'
            ? 'rgba(14, 165, 233, 0.96)'
            : tier === 'B2'
              ? 'rgba(2, 132, 199, 0.94)'
              : tier === 'C'
                ? 'rgba(3, 105, 161, 0.92)'
                : 'rgba(14, 165, 233, 0.96)'
    return {
      color,
      borderColor: 'rgba(224, 242, 254, 0.98)',
      shape: 'ellipse',
      size: 20 + Math.min(26, weightedDegree * 1.18),
    }
  }
  if (data.kind === 'logic') {
    return {
      color: 'rgba(52, 211, 153, 0.94)',
      borderColor: 'rgba(209, 250, 229, 0.92)',
      shape: 'round-rectangle',
      size: 16 + Math.min(20, weightedDegree * 0.8),
    }
  }
  if (data.kind === 'claim') {
    return {
      color: 'rgba(251, 146, 60, 0.92)',
      borderColor: 'rgba(255, 237, 213, 0.92)',
      shape: 'round-rectangle',
      size: 14 + Math.min(18, weightedDegree * 0.7),
    }
  }
  if (data.kind === 'prop' || data.kind === 'proposition') {
    if (data.state === 'challenged') {
      return {
        color: 'rgba(248, 113, 113, 0.92)',
        borderColor: 'rgba(254, 226, 226, 0.92)',
        shape: 'diamond',
        size: 16 + Math.min(20, weightedDegree * 0.8),
      }
    }
    if (data.state === 'superseded') {
      return {
        color: 'rgba(148, 163, 184, 0.84)',
        borderColor: 'rgba(226, 232, 240, 0.84)',
        shape: 'diamond',
        size: 14 + Math.min(18, weightedDegree * 0.7),
      }
    }
    return {
      color: 'rgba(250, 204, 21, 0.9)',
      borderColor: 'rgba(254, 243, 199, 0.9)',
      shape: 'diamond',
      size: 15 + Math.min(20, weightedDegree * 0.75),
    }
  }
  if (data.kind === 'group') {
    return {
      color: 'rgba(45, 212, 191, 0.90)',
      borderColor: 'rgba(204, 251, 241, 0.9)',
      shape: 'round-rectangle',
      size: 20 + Math.min(24, weightedDegree),
    }
  }
  if (data.kind === 'entity') {
    return {
      color: 'rgba(20, 184, 166, 0.90)',
      borderColor: 'rgba(153, 246, 228, 0.88)',
      shape: 'ellipse',
      size: 13 + Math.min(16, weightedDegree * 0.65),
    }
  }
  if (data.kind === 'citation') {
    return {
      color: 'rgba(148, 163, 184, 0.7)',
      borderColor: 'rgba(203, 213, 225, 0.75)',
      shape: 'ellipse',
      size: 10 + Math.min(12, weightedDegree * 0.5),
    }
  }
  return {
    color: 'rgba(56, 189, 248, 0.9)',
    borderColor: 'rgba(186, 230, 253, 0.88)',
    shape: 'ellipse',
    size: 14 + Math.min(16, weightedDegree * 0.7),
  }
}

function edgeVisual(kind: string, weight: number): EdgeVisual {
  const width = 1 + clamp(weight, 0, 1) * 2.8
  if (kind === 'cites') {
    return { color: 'rgba(125, 211, 252, 0.6)', lineStyle: 'solid', arrow: 'triangle', width, opacity: 0.9 }
  }
  if (kind === 'supports') {
    return { color: 'rgba(74, 222, 128, 0.65)', lineStyle: 'solid', arrow: 'triangle', width, opacity: 0.9 }
  }
  if (kind === 'challenges') {
    return { color: 'rgba(248, 113, 113, 0.7)', lineStyle: 'dashed', arrow: 'triangle', width, opacity: 0.9 }
  }
  if (kind === 'supersedes') {
    return { color: 'rgba(250, 204, 21, 0.68)', lineStyle: 'solid', arrow: 'triangle', width, opacity: 0.88 }
  }
  if (kind === 'similar') {
    return { color: 'rgba(148, 163, 184, 0.55)', lineStyle: 'dashed', arrow: 'none', width, opacity: 0.82 }
  }
  if (kind === 'maps_to') {
    return { color: 'rgba(20, 184, 166, 0.62)', lineStyle: 'solid', arrow: 'triangle', width, opacity: 0.88 }
  }
  if (kind === 'relates_to') {
    return { color: 'rgba(56, 189, 248, 0.5)', lineStyle: 'solid', arrow: 'none', width, opacity: 0.78 }
  }
  if (kind === 'contains') {
    return { color: 'rgba(94, 234, 212, 0.45)', lineStyle: 'solid', arrow: 'none', width, opacity: 0.75 }
  }
  if (kind === 'evidenced_by') {
    return { color: 'rgba(134, 239, 172, 0.48)', lineStyle: 'dashed', arrow: 'none', width, opacity: 0.75 }
  }
  return { color: 'rgba(148, 163, 184, 0.5)', lineStyle: 'solid', arrow: 'none', width, opacity: 0.72 }
}

function colorOfKind(kind: string) {
  const pseudo: GraphNodeData = { id: `kind:${kind}`, label: kind, kind }
  return nodeVisual(pseudo, 8).color
}

function edgeScore(edge: InternalEdge) {
  const weight = Number(edge.weight ?? 0)
  const mentions = Number(edge.totalMentions ?? 0)
  return weight * 100 + mentions
}

function buildAggregateBackboneEdges(
  dedupEdges: InternalEdge[],
  nodeMap: Map<string, GraphNodeData>,
  nodeElements: GraphNodeData[],
  degreeMap: Map<string, number>,
  selectedNodeId?: string,
): InternalEdge[] {
  if (!dedupEdges.length) return []

  const sortedEdges = [...dedupEdges]
    .filter((edge) => {
      const source = String(edge.source ?? '')
      const target = String(edge.target ?? '')
      if (!source || !target || source === target) return false
      return nodeMap.has(source) && nodeMap.has(target)
    })
    .sort((a, b) => edgeScore(b) - edgeScore(a))

  if (!sortedEdges.length) return []

  const nodeCount = Math.max(1, nodeElements.length)
  const hardCap = clamp(Math.round(74 + Math.sqrt(nodeCount) * 9.5), 96, 168) + (selectedNodeId ? 24 : 0)
  const perSourceCap = nodeCount >= 120 ? 2 : 3
  const perTargetCap = nodeCount >= 120 ? 1 : 2
  const backboneBudget = Math.max(30, Math.round(hardCap * 0.45))
  const coverageBudget = Math.max(44, Math.round(hardCap * 0.72))
  const minimumBudget = Math.max(24, Math.round(Math.sqrt(nodeCount) * 4))

  const chosen = new Set<string>()
  const sourceCounts = new Map<string, number>()
  const targetCounts = new Map<string, number>()
  const nodeCoverage = new Map<string, number>()
  const incidentMap = new Map<string, InternalEdge[]>()
  const rendered: InternalEdge[] = []

  for (const edge of sortedEdges) {
    const source = String(edge.source ?? '')
    const target = String(edge.target ?? '')
    const sourceList = incidentMap.get(source) ?? []
    sourceList.push(edge)
    incidentMap.set(source, sourceList)
    const targetList = incidentMap.get(target) ?? []
    targetList.push(edge)
    incidentMap.set(target, targetList)
  }

  const addEdge = (
    edge: InternalEdge,
    options?: {
      sourceCap?: number
      targetCap?: number
      ignoreCap?: boolean
    },
  ): boolean => {
    if (rendered.length >= hardCap) return false
    const id = String(edge.id)
    if (chosen.has(id)) return false

    const source = String(edge.source ?? '')
    const target = String(edge.target ?? '')
    if (!source || !target || source === target) return false

    const sourceCap = Math.max(1, options?.sourceCap ?? perSourceCap)
    const targetCap = Math.max(1, options?.targetCap ?? perTargetCap)
    const sourceCount = sourceCounts.get(source) ?? 0
    const targetCount = targetCounts.get(target) ?? 0
    if (!options?.ignoreCap && (sourceCount >= sourceCap || targetCount >= targetCap)) return false

    chosen.add(id)
    rendered.push(edge)
    sourceCounts.set(source, sourceCount + 1)
    targetCounts.set(target, targetCount + 1)
    nodeCoverage.set(source, (nodeCoverage.get(source) ?? 0) + 1)
    nodeCoverage.set(target, (nodeCoverage.get(target) ?? 0) + 1)
    return true
  }

  for (const edge of sortedEdges) {
    addEdge(edge, { sourceCap: 2, targetCap: 2 })
    if (rendered.length >= backboneBudget) break
  }

  const nodesByDegree = [...nodeElements].sort((a, b) => (degreeMap.get(b.id) ?? 0) - (degreeMap.get(a.id) ?? 0))
  for (const node of nodesByDegree) {
    if (rendered.length >= coverageBudget) break
    if ((nodeCoverage.get(node.id) ?? 0) > 0) continue
    const candidates = incidentMap.get(node.id) ?? []
    for (const edge of candidates) {
      if (addEdge(edge, { sourceCap: 3, targetCap: 3 })) break
    }
  }

  if (selectedNodeId) {
    const selectedEdges = [...(incidentMap.get(selectedNodeId) ?? [])].sort((a, b) => edgeScore(b) - edgeScore(a))
    const selectedBudget = clamp(Math.round(hardCap * 0.26), 12, 36)
    let selectedAdded = 0
    for (const edge of selectedEdges) {
      if (addEdge(edge, { ignoreCap: true })) {
        selectedAdded += 1
      }
      if (selectedAdded >= selectedBudget || rendered.length >= hardCap) break
    }
  }

  for (const edge of sortedEdges) {
    addEdge(edge, { sourceCap: perSourceCap, targetCap: perTargetCap })
    if (rendered.length >= hardCap) break
  }

  if (rendered.length < minimumBudget) {
    for (const edge of sortedEdges) {
      addEdge(edge, { ignoreCap: true })
      if (rendered.length >= minimumBudget || rendered.length >= hardCap) break
    }
  }

  return rendered
}

function buildStyle(): cytoscape.StylesheetStyle[] {
  return [
    {
      selector: 'node',
      style: {
        width: 'data(size)',
        height: 'data(size)',
        shape: 'data(shape)',
        'background-color': 'data(color)',
        'background-opacity': 0.95,
        'border-width': 1.8,
        'border-color': 'data(borderColor)',
        'border-opacity': 0.92,
        'underlay-color': 'data(color)',
        'underlay-opacity': 0.12,
        'underlay-padding': 8,
        'underlay-shape': 'ellipse',
        label: 'data(shortLabel)',
        color: 'rgba(237, 247, 255, 0.96)',
        'font-size': 'mapData(size, 10, 44, 8, 13)',
        'font-family': '"Fira Sans","IBM Plex Sans","Noto Sans SC",sans-serif',
        'font-weight': 600,
        'text-wrap': 'wrap',
        'text-max-width': '124px',
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-outline-color': 'rgba(2, 8, 22, 0.7)',
        'text-outline-width': 2,
        'min-zoomed-font-size': 11,
        'text-background-color': 'rgba(3, 10, 24, 0.66)',
        'text-background-opacity': 0.86,
        'text-background-padding': 2,
        'text-background-shape': 'roundrectangle',
      } as unknown as cytoscape.Css.Node,
    },
    {
      selector: 'node[__decorative = 1]',
      style: {
        events: 'no',
        'overlay-opacity': 0,
        'underlay-opacity': 0,
        'text-background-opacity': 0,
        'z-index-compare': 'manual',
        'z-index': 1,
      } as unknown as cytoscape.Css.Node,
    },
    {
      selector: 'node[decorType = "zone"]',
      style: {
        width: 'data(width)',
        height: 'data(height)',
        shape: 'round-rectangle',
        'background-color': 'data(color)',
        'background-opacity': 0.11,
        'border-width': 1,
        'border-color': 'data(borderColor)',
        'border-opacity': 0.28,
        label: 'data(label)',
        color: 'rgba(203, 224, 247, 0.56)',
        'font-size': 10,
        'font-family': '"Fira Sans","IBM Plex Sans","Noto Sans SC",sans-serif',
        'font-weight': 500,
        'text-valign': 'top',
        'text-margin-y': -6,
        'text-outline-width': 0,
        opacity: 1,
        'z-index': 1,
      } as unknown as cytoscape.Css.Node,
    },
    {
      selector: 'node[decorType = "hull"]',
      style: {
        width: 'data(width)',
        height: 'data(height)',
        shape: 'round-rectangle',
        'background-color': 'data(color)',
        'background-opacity': 0.06,
        'border-width': 1,
        'border-color': 'data(borderColor)',
        'border-opacity': 0.24,
        label: 'data(label)',
        color: 'rgba(176, 212, 241, 0.44)',
        'font-size': 9,
        'font-family': '"Fira Sans","IBM Plex Sans","Noto Sans SC",sans-serif',
        'text-valign': 'center',
        'text-outline-width': 0,
        'text-background-opacity': 0,
        opacity: 1,
        'z-index': 3,
      } as unknown as cytoscape.Css.Node,
    },
    {
      selector: 'node[decorType = "anchor"]',
      style: {
        width: 1,
        height: 1,
        shape: 'ellipse',
        'background-opacity': 0,
        'border-width': 0,
        label: '',
        opacity: 0,
        'z-index': 2,
      } as unknown as cytoscape.Css.Node,
    },
    {
      selector: 'node:selected',
      style: {
        'border-color': '#bef264',
        'border-width': 3.2,
        'overlay-color': 'rgba(190, 242, 100, 0.2)',
        'overlay-padding': 10,
        'overlay-opacity': 0.9,
        'underlay-color': '#bef264',
        'underlay-opacity': 0.35,
        'underlay-padding': 14,
        'z-index': 999,
      } as unknown as cytoscape.Css.Node,
    },
    {
      selector: 'node.faded',
      style: { opacity: 0.14 },
    },
    {
      selector: 'edge',
      style: {
        width: 'data(width)',
        'line-color': 'data(edgeColor)',
        'line-style': 'data(lineStyle)',
        'line-opacity': 'data(edgeOpacity)',
        'target-arrow-shape': 'data(arrow)',
        'target-arrow-color': 'data(edgeColor)',
        'curve-style': 'bezier',
        'control-point-distances': 0,
        'control-point-weights': 0.5,
        'arrow-scale': 0.75,
      } as unknown as cytoscape.Css.Edge,
    },
    {
      selector: 'edge[decorType = "flow"]',
      style: {
        width: 'data(width)',
        'line-color': 'data(edgeColor)',
        'line-style': 'solid',
        'line-opacity': 0.3,
        'target-arrow-shape': 'none',
        'target-arrow-color': 'data(edgeColor)',
        'arrow-scale': 0.5,
        'curve-style': 'bezier',
        'control-point-distances': 0,
        'control-point-weights': 0.5,
        events: 'no',
        'z-index-compare': 'manual',
        'z-index': 2,
      } as unknown as cytoscape.Css.Edge,
    },
    {
      selector: 'edge.faded',
      style: { opacity: 0.03 },
    },
  ]
}

function relaxBuckets(positionMap: Map<string, PositionedNode>, buckets: Map<string, string[]>) {
  for (const ids of buckets.values()) {
    if (ids.length <= 1) continue
    for (let round = 0; round < RELAX_ROUNDS; round += 1) {
      for (let i = 0; i < ids.length; i += 1) {
        const a = positionMap.get(ids[i])
        if (!a) continue
        for (let j = i + 1; j < ids.length; j += 1) {
          const b = positionMap.get(ids[j])
          if (!b) continue

          const dx = a.x - b.x
          const dy = a.y - b.y
          const dist = Math.hypot(dx, dy) || 0.001
          if (dist >= MIN_NODE_DISTANCE) continue

          const push = (MIN_NODE_DISTANCE - dist) / 2
          const ux = dx / dist
          const uy = dy / dist
          a.x += ux * push
          a.y += uy * push
          b.x -= ux * push
          b.y -= uy * push
        }
      }

      for (const id of ids) {
        const pos = positionMap.get(id)
        if (!pos) continue
        pos.x = pos.x * 0.86 + pos.anchorX * 0.14
        pos.y = pos.y * 0.86 + pos.anchorY * 0.14
      }
    }
  }
}

function hashSeed(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return Math.abs(h >>> 0)
}

function applyRelationRelaxation(
  positionMap: Map<string, PositionedNode>,
  anchorMap: Map<string, { x: number; y: number }>,
  bucketByNode: Map<string, string>,
  bucketNodeIds: Map<string, string[]>,
  edges: InternalEdge[],
) {
  const nodeIds = Array.from(positionMap.keys())
  if (!nodeIds.length) return

  const steps = clamp(Math.round(18 + Math.sqrt(nodeIds.length) * 3.5), 24, 58)

  for (let step = 0; step < steps; step += 1) {
    const forceMap = new Map<string, { x: number; y: number }>()
    for (const id of nodeIds) forceMap.set(id, { x: 0, y: 0 })

    for (const id of nodeIds) {
      const pos = positionMap.get(id)
      const anchor = anchorMap.get(id)
      const f = forceMap.get(id)
      if (!pos || !anchor || !f) continue
      f.x += (anchor.x - pos.x) * ANCHOR_PULL
      f.y += (anchor.y - pos.y) * ANCHOR_PULL
    }

    for (const edge of edges) {
      const sourceId = String(edge.source ?? '')
      const targetId = String(edge.target ?? '')
      if (sourceId === targetId) continue

      const sourcePos = positionMap.get(sourceId)
      const targetPos = positionMap.get(targetId)
      const sourceForce = forceMap.get(sourceId)
      const targetForce = forceMap.get(targetId)
      if (!sourcePos || !targetPos || !sourceForce || !targetForce) continue

      const dx = targetPos.x - sourcePos.x
      const dy = targetPos.y - sourcePos.y
      const dist = Math.hypot(dx, dy) || 0.001
      const ux = dx / dist
      const uy = dy / dist

      const sameBucket = bucketByNode.get(sourceId) === bucketByNode.get(targetId)
      const desired = sameBucket ? EDGE_SPRING_IN_BUCKET : EDGE_SPRING_CROSS_BUCKET
      const spring = (dist - desired) * EDGE_SPRING_K
      const weight = clamp(Number(edge.weight ?? 0.5), 0.12, 1.2)

      sourceForce.x += ux * spring * weight
      sourceForce.y += uy * spring * weight
      targetForce.x -= ux * spring * weight
      targetForce.y -= uy * spring * weight
    }

    const cooling = clamp(1 - step / (steps * 1.28), 0.35, 1)
    for (const id of nodeIds) {
      const pos = positionMap.get(id)
      const force = forceMap.get(id)
      if (!pos || !force) continue
      pos.x += clamp(force.x * cooling, -10, 10)
      pos.y += clamp(force.y * cooling, -10, 10)
    }

    if (step % 6 === 0 || step === steps - 1) {
      relaxBuckets(positionMap, bucketNodeIds)
    }
  }
}

function buildSingleLaneNetworkPositions(
  nodes: GraphNodeData[],
  edges: InternalEdge[],
  yearToX: Map<number, number>,
  unknownX: number,
): Map<string, { x: number; y: number }> {
  if (!nodes.length) return new Map()

  const nodeSet = new Set(nodes.map((node) => node.id))
  const cy = cytoscape({
    headless: true,
    styleEnabled: false,
    elements: [
      ...nodes.map((node) => {
        const seed = hashSeed(node.id)
        const baseX = (seed % 1000) - 500
        const baseY = (Math.floor(seed / 1000) % 1000) - 500
        return {
          group: 'nodes' as const,
          data: { id: node.id },
          position: { x: baseX, y: baseY },
        }
      }),
      ...edges
        .filter((edge) => {
          const source = String(edge.source ?? '')
          const target = String(edge.target ?? '')
          return source !== target && nodeSet.has(source) && nodeSet.has(target)
        })
        .map((edge) => ({
          group: 'edges' as const,
          data: {
            id: String(edge.id),
            source: String(edge.source ?? ''),
            target: String(edge.target ?? ''),
          },
        })),
    ],
  })

  try {
    cy
      .layout({
        name: 'cose',
        animate: false,
        randomize: false,
        fit: false,
        nodeRepulsion: 200000,
        idealEdgeLength: 136,
        edgeElasticity: 0.16,
        gravity: 0.28,
        numIter: 2200,
      } as unknown as cytoscape.LayoutOptions)
      .run()

    const bb = cy.nodes().boundingBox({
      includeLabels: false,
      includeMainLabels: false,
      includeOverlays: false,
    })
    const width = Math.max(bb.w, 1)
    const height = Math.max(bb.h, 1)

    const positions = new Map<string, { x: number; y: number }>()
    for (const node of nodes) {
      const cyNode = cy.getElementById(node.id)
      if (!cyNode.nonempty() || !cyNode.isNode()) continue
      const pos = (cyNode as unknown as cytoscape.NodeSingular).position()
      const nx = ((pos.x - bb.x1) / width - 0.5) * 2
      const ny = ((pos.y - bb.y1) / height - 0.5) * 2

      const year = validYear(node.year)
      const yearX = year === null ? unknownX : (yearToX.get(year) ?? unknownX)
      const x = yearX * 0.42 + nx * 760
      const y = ny * 390 + Math.sin((yearX / Math.max(YEAR_GAP, 1)) * 0.72) * 96

      positions.set(node.id, { x, y })
    }

    return positions
  } finally {
    cy.destroy()
  }
}

function buildRawMeshLayout(
  nodes: GraphNodeData[],
  edges: InternalEdge[],
  meshLaneLabel: string,
): {
  positions: Map<string, { x: number; y: number }>
  meta: LayoutMeta
} {
  const positions = new Map<string, { x: number; y: number }>()
  if (!nodes.length) {
    return {
      positions,
      meta: {
        yearAnchors: [],
        yearAxis: [],
        laneSummary: [meshLaneLabel],
      },
    }
  }

  const nodeSet = new Set(nodes.map((node) => node.id))
  const cy = cytoscape({
    headless: true,
    styleEnabled: false,
    elements: [
      ...nodes.map((node) => {
        const seed = hashSeed(node.id)
        const baseX = (seed % 1200) - 600
        const baseY = (Math.floor(seed / 1200) % 1200) - 600
        return {
          group: 'nodes' as const,
          data: { id: node.id },
          position: { x: baseX, y: baseY },
        }
      }),
      ...edges
        .filter((edge) => {
          const source = String(edge.source ?? '')
          const target = String(edge.target ?? '')
          return source !== target && nodeSet.has(source) && nodeSet.has(target)
        })
        .map((edge) => ({
          group: 'edges' as const,
          data: {
            id: String(edge.id),
            source: String(edge.source ?? ''),
            target: String(edge.target ?? ''),
          },
        })),
    ],
  })

  try {
    cy
      .layout({
        name: 'cose',
        animate: false,
        randomize: false,
        fit: false,
        nodeRepulsion: 240000,
        idealEdgeLength: 146,
        edgeElasticity: 0.22,
        gravity: 0.2,
        numIter: 2200,
      } as unknown as cytoscape.LayoutOptions)
      .run()

    const bb = cy.nodes().boundingBox({
      includeLabels: false,
      includeMainLabels: false,
      includeOverlays: false,
    })
    const width = Math.max(bb.w, 1)
    const height = Math.max(bb.h, 1)

    for (const node of nodes) {
      const cyNode = cy.getElementById(node.id)
      if (!cyNode.nonempty() || !cyNode.isNode()) {
        const seed = hashSeed(node.id)
        positions.set(node.id, {
          x: (seed % 1800) - 900,
          y: ((Math.floor(seed / 1800) % 1200) - 600) * 0.9,
        })
        continue
      }
      const pos = (cyNode as unknown as cytoscape.NodeSingular).position()
      const nx = ((pos.x - bb.x1) / width - 0.5) * 2
      const ny = ((pos.y - bb.y1) / height - 0.5) * 2
      positions.set(node.id, { x: nx * 940, y: ny * 540 })
    }
  } finally {
    cy.destroy()
  }

  const degreeMap = new Map<string, number>()
  for (const edge of edges) {
    const source = String(edge.source ?? '')
    const target = String(edge.target ?? '')
    degreeMap.set(source, (degreeMap.get(source) ?? 0) + 1)
    degreeMap.set(target, (degreeMap.get(target) ?? 0) + 1)
  }
  const sizeByNode = new Map<string, number>()
  for (const node of nodes) {
    sizeByNode.set(node.id, nodeVisual(node, degreeMap.get(node.id) ?? 0).size)
  }

  const edgePairs = edges
    .map((edge) => {
      const source = String(edge.source ?? '')
      const target = String(edge.target ?? '')
      if (!source || !target || source === target) return null
      if (!positions.has(source) || !positions.has(target)) return null
      return { source, target }
    })
    .filter((item): item is { source: string; target: string } => item !== null)

  const ids = Array.from(positions.keys())
  const forceMap = new Map<string, { x: number; y: number }>()
  const rounds = clamp(Math.round(28 + Math.sqrt(ids.length) * 1.05), 30, 44)
  for (let round = 0; round < rounds; round += 1) {
    for (const id of ids) forceMap.set(id, { x: 0, y: 0 })

    for (let i = 0; i < ids.length; i += 1) {
      const aId = ids[i]
      const a = positions.get(aId)
      if (!a) continue
      const aSize = sizeByNode.get(aId) ?? 12
      for (let j = i + 1; j < ids.length; j += 1) {
        const bId = ids[j]
        const b = positions.get(bId)
        if (!b) continue
        const bSize = sizeByNode.get(bId) ?? 12

        const dx = a.x - b.x
        const dy = a.y - b.y
        const dist = Math.hypot(dx, dy) || 0.001
        const minDist = (aSize + bSize) * 0.72 + 13
        if (dist >= minDist) continue
        const strength = (minDist - dist) / minDist
        const push = strength * clamp(4.8 - round * 0.06, 2.1, 4.8)
        const ux = dx / dist
        const uy = dy / dist
        const af = forceMap.get(aId)
        const bf = forceMap.get(bId)
        if (!af || !bf) continue
        af.x += ux * push
        af.y += uy * push
        bf.x -= ux * push
        bf.y -= uy * push
      }
    }

    for (const pair of edgePairs) {
      const source = positions.get(pair.source)
      const target = positions.get(pair.target)
      const sf = forceMap.get(pair.source)
      const tf = forceMap.get(pair.target)
      if (!source || !target || !sf || !tf) continue

      const dx = target.x - source.x
      const dy = target.y - source.y
      const dist = Math.hypot(dx, dy) || 0.001
      const sourceSize = sizeByNode.get(pair.source) ?? 12
      const targetSize = sizeByNode.get(pair.target) ?? 12
      const desired = (sourceSize + targetSize) * 1.2 + 92
      const spring = (dist - desired) * 0.0018
      const ux = dx / dist
      const uy = dy / dist

      sf.x += ux * spring
      sf.y += uy * spring
      tf.x -= ux * spring
      tf.y -= uy * spring
    }

    const cooling = clamp(1 - round / (rounds * 1.16), 0.35, 1)
    for (const id of ids) {
      const pos = positions.get(id)
      const force = forceMap.get(id)
      if (!pos || !force) continue
      force.x += -pos.x * 0.00072
      force.y += -pos.y * 0.00068
      pos.x += clamp(force.x * cooling, -14, 14)
      pos.y += clamp(force.y * cooling, -12, 12)
      pos.x = clamp(pos.x, -1720, 1720)
      pos.y = clamp(pos.y, -1020, 1020)
    }
  }

  for (let settle = 0; settle < 12; settle += 1) {
    for (let i = 0; i < ids.length; i += 1) {
      const aId = ids[i]
      const a = positions.get(aId)
      if (!a) continue
      const aSize = sizeByNode.get(aId) ?? 12
      for (let j = i + 1; j < ids.length; j += 1) {
        const bId = ids[j]
        const b = positions.get(bId)
        if (!b) continue
        const bSize = sizeByNode.get(bId) ?? 12
        const dx = a.x - b.x
        const dy = a.y - b.y
        const dist = Math.hypot(dx, dy) || 0.001
        const minDist = (aSize + bSize) * 0.84 + 12
        if (dist >= minDist) continue
        const push = ((minDist - dist) / 2) * clamp(0.82 - settle * 0.05, 0.28, 0.82)
        const ux = dx / dist
        const uy = dy / dist
        a.x += ux * push
        a.y += uy * push
        b.x -= ux * push
        b.y -= uy * push
      }
    }
  }

  return {
    positions,
    meta: {
      yearAnchors: [],
      yearAxis: [],
      laneSummary: [meshLaneLabel],
    },
  }
}

function buildCockpitDecorations(
  nodes: GraphNodeData[],
  positions: Map<string, { x: number; y: number }>,
  unknownLabel: string,
): PositionedElement[] {
  if (!nodes.length) return []

  type YearBucket = {
    key: string
    year: number | null
    label: string
    ids: string[]
    center: { x: number; y: number }
    bounds: { minX: number; maxX: number; minY: number; maxY: number }
  }

  const yearMap = new Map<string, YearBucket>()
  for (const node of nodes) {
    const pos = positions.get(node.id)
    if (!pos) continue
    const year = validYear(node.year)
    const key = year === null ? 'unknown' : String(year)
    const label = year === null ? unknownLabel : String(year)

    const existing = yearMap.get(key)
    if (!existing) {
      yearMap.set(key, {
        key,
        year,
        label,
        ids: [node.id],
        center: { x: pos.x, y: pos.y },
        bounds: { minX: pos.x, maxX: pos.x, minY: pos.y, maxY: pos.y },
      })
      continue
    }

    existing.ids.push(node.id)
    existing.center.x += pos.x
    existing.center.y += pos.y
    existing.bounds.minX = Math.min(existing.bounds.minX, pos.x)
    existing.bounds.maxX = Math.max(existing.bounds.maxX, pos.x)
    existing.bounds.minY = Math.min(existing.bounds.minY, pos.y)
    existing.bounds.maxY = Math.max(existing.bounds.maxY, pos.y)
  }

  const buckets = Array.from(yearMap.values())
    .map((bucket) => ({
      ...bucket,
      center: {
        x: bucket.center.x / Math.max(1, bucket.ids.length),
        y: bucket.center.y / Math.max(1, bucket.ids.length),
      },
    }))
    .sort((a, b) => {
      if (a.year === null && b.year === null) return 0
      if (a.year === null) return 1
      if (b.year === null) return -1
      return a.year - b.year
    })

  if (!buckets.length) return []

  const decorations: PositionedElement[] = []
  const hullPalette = [
    'rgba(59, 130, 246, 0.22)',
    'rgba(14, 165, 233, 0.22)',
    'rgba(45, 212, 191, 0.22)',
    'rgba(99, 102, 241, 0.2)',
  ]
  const zonePalette = [
    'rgba(15, 23, 42, 0.85)',
    'rgba(7, 24, 43, 0.82)',
    'rgba(6, 31, 50, 0.84)',
  ]
  const zoneBorder = [
    'rgba(59, 130, 246, 0.45)',
    'rgba(14, 165, 233, 0.45)',
    'rgba(45, 212, 191, 0.45)',
  ]

  const phaseCount = buckets.length <= 3 ? 1 : buckets.length <= 7 ? 2 : 3
  const phaseNames = ['Foundation', 'Expansion', 'Frontier']
  const phaseBuckets: YearBucket[][] = Array.from({ length: phaseCount }, () => [])
  for (let i = 0; i < buckets.length; i += 1) {
    const idx = Math.min(phaseCount - 1, Math.floor((i / Math.max(1, buckets.length)) * phaseCount))
    phaseBuckets[idx].push(buckets[i])
  }

  const hullKeys = new Set(
    [...buckets]
      .sort((a, b) => b.ids.length - a.ids.length)
      .slice(0, 5)
      .map((bucket) => bucket.key),
  )

  for (let idx = 0; idx < phaseBuckets.length; idx += 1) {
    const group = phaseBuckets[idx]
    if (!group.length) continue
    const minX = Math.min(...group.map((item) => item.bounds.minX))
    const maxX = Math.max(...group.map((item) => item.bounds.maxX))
    const minY = Math.min(...group.map((item) => item.bounds.minY))
    const maxY = Math.max(...group.map((item) => item.bounds.maxY))
    const width = Math.max(340, maxX - minX + 280)
    const height = Math.max(300, maxY - minY + 250)
    decorations.push({
      group: 'nodes',
      data: {
        id: `decor:zone:${idx}`,
        __decorative: 1,
        decorType: 'zone',
        label: phaseNames[Math.min(phaseNames.length - 1, idx)],
        width,
        height,
        color: zonePalette[idx % zonePalette.length],
        borderColor: zoneBorder[idx % zoneBorder.length],
      },
      position: {
        x: (minX + maxX) / 2,
        y: (minY + maxY) / 2,
      },
    })
  }

  const anchorNodes: Array<{ id: string; key: string; count: number; center: { x: number; y: number } }> = []
  for (let idx = 0; idx < buckets.length; idx += 1) {
    const bucket = buckets[idx]
    if (hullKeys.has(bucket.key) && bucket.ids.length >= 8) {
      const width = Math.max(120, bucket.bounds.maxX - bucket.bounds.minX + 70)
      const height = Math.max(90, bucket.bounds.maxY - bucket.bounds.minY + 62)
      decorations.push({
        group: 'nodes',
        data: {
          id: `decor:hull:${bucket.key}`,
          __decorative: 1,
          decorType: 'hull',
          label: bucket.label,
          width,
          height,
          color: hullPalette[idx % hullPalette.length],
          borderColor: 'rgba(148, 197, 255, 0.55)',
        },
        position: {
          x: bucket.center.x,
          y: bucket.center.y,
        },
      })
    }

    const anchorId = `decor:anchor:${bucket.key}`
    anchorNodes.push({ id: anchorId, key: bucket.key, count: bucket.ids.length, center: bucket.center })
    decorations.push({
      group: 'nodes',
      data: {
        id: anchorId,
        __decorative: 1,
        decorType: 'anchor',
        label: '',
        size: 1,
        color: 'rgba(0,0,0,0)',
        borderColor: 'rgba(0,0,0,0)',
        shape: 'ellipse',
      },
      position: {
        x: bucket.center.x,
        y: bucket.center.y,
      },
    })
  }

  for (let idx = 0; idx < anchorNodes.length - 1; idx += 1) {
    const a = anchorNodes[idx]
    const b = anchorNodes[idx + 1]
    const strength = Math.log2((a.count + b.count) / 2 + 1)
    decorations.push({
      group: 'edges',
      data: {
        id: `decor:flow:${a.key}:${b.key}`,
        source: a.id,
        target: b.id,
        __decorative: 1,
        decorType: 'flow',
        kind: 'flow',
        weight: 1,
        totalMentions: 0,
        purposeLabels: [],
        width: 0.8 + strength * 0.62,
        edgeColor: 'rgba(125, 211, 252, 0.3)',
        lineStyle: 'solid',
        edgeOpacity: 0.34,
        arrow: 'none',
        bundleOffset: 0,
      },
    })
  }

  return decorations
}

function buildCockpitLayout(
  nodes: GraphNodeData[],
  edges: InternalEdge[],
  degreeMap: Map<string, number>,
  unknownLabel: string,
  getKindLabel: (kind: string) => string,
): {
  positions: Map<string, { x: number; y: number }>
  meta: LayoutMeta
} {
  const knownYears = Array.from(
    new Set(
      nodes
        .map((node) => validYear(node.year))
        .filter((year): year is number => year !== null),
    ),
  ).sort((a, b) => a - b)

  const yearAnchors = knownYears.map((year) => ({ key: String(year), label: String(year) }))
  if (nodes.some((node) => validYear(node.year) === null)) {
    yearAnchors.push({ key: 'unknown', label: unknownLabel })
  }

  const yearRankByKey = new Map<string, number>()
  const yearToX = new Map<number, number>()
  if (knownYears.length > 0) {
    const center = (knownYears.length - 1) / 2
    for (let idx = 0; idx < knownYears.length; idx += 1) {
      yearToX.set(knownYears[idx], (idx - center) * YEAR_GAP)
      yearRankByKey.set(String(knownYears[idx]), idx - center)
    }
  }
  yearRankByKey.set('unknown', (knownYears.length - 1) / 2 + 1.1)
  const unknownX =
    knownYears.length > 0
      ? (knownYears.length - 1 - (knownYears.length - 1) / 2 + 1.15) * YEAR_GAP
      : YEAR_GAP * 0.75

  const yearAxis = knownYears.map((year) => ({
    key: String(year),
    label: String(year),
    x: yearToX.get(year) ?? 0,
  }))
  if (nodes.some((node) => validYear(node.year) === null)) {
    yearAxis.push({ key: 'unknown', label: unknownLabel, x: unknownX })
  }

  const laneKinds = Array.from(new Set(nodes.map((node) => String(node.kind ?? 'unknown')))).sort((a, b) => {
    const diff = kindOrder(a) - kindOrder(b)
    if (diff !== 0) return diff
    return a.localeCompare(b)
  })
  const laneSummary = laneKinds.map((kind) => getKindLabel(kind))

  const laneToY = new Map<string, number>()
  const laneCenter = (laneKinds.length - 1) / 2
  for (let idx = 0; idx < laneKinds.length; idx += 1) {
    laneToY.set(laneKinds[idx], (idx - laneCenter) * LANE_GAP)
  }
  const singleLane = laneKinds.length <= 1

  const laneYearBuckets = new Map<string, GraphNodeData[]>()
  const bucketByNode = new Map<string, string>()
  const bucketNodeIds = new Map<string, string[]>()

  for (const node of nodes) {
    const lane = String(node.kind ?? 'unknown')
    const year = validYear(node.year)
    const yearKey = year === null ? 'unknown' : String(year)
    const bucketKey = `${lane}|${yearKey}`

    const bucket = laneYearBuckets.get(bucketKey) ?? []
    bucket.push(node)
    laneYearBuckets.set(bucketKey, bucket)

    bucketByNode.set(node.id, bucketKey)
    const ids = bucketNodeIds.get(bucketKey) ?? []
    ids.push(node.id)
    bucketNodeIds.set(bucketKey, ids)
  }

  const positionMap = new Map<string, PositionedNode>()
  const anchorMap = new Map<string, { x: number; y: number }>()

  if (singleLane && nodes.length >= 120) {
    const networkPositions = buildSingleLaneNetworkPositions(nodes, edges, yearToX, unknownX)
    for (const node of nodes) {
      const pos = networkPositions.get(node.id)
      if (pos) {
        positionMap.set(node.id, { x: pos.x, y: pos.y, anchorX: pos.x, anchorY: pos.y })
        anchorMap.set(node.id, { x: pos.x, y: pos.y })
        continue
      }

      const year = validYear(node.year)
      const yearX = year === null ? unknownX : (yearToX.get(year) ?? unknownX)
      const fallback = { x: yearX, y: (hashSeed(node.id) % 400) - 200 }
      positionMap.set(node.id, { x: fallback.x, y: fallback.y, anchorX: fallback.x, anchorY: fallback.y })
      anchorMap.set(node.id, fallback)
    }
  } else {
    for (const [bucketKey, bucketNodes] of laneYearBuckets.entries()) {
      const [lane, yearKey] = bucketKey.split('|')
      const laneY = laneToY.get(lane) ?? 0
      const yearRank = yearRankByKey.get(yearKey) ?? 0
      const year = Number(yearKey)
      const baseX = Number.isFinite(year) ? (yearToX.get(year) ?? unknownX) : unknownX
      const baseAngle = (hashSeed(bucketKey) % 628) / 100

      const sortedNodes = [...bucketNodes].sort((a, b) => {
        const degreeDiff = (degreeMap.get(b.id) ?? 0) - (degreeMap.get(a.id) ?? 0)
        if (degreeDiff !== 0) return degreeDiff
        return String(a.label ?? '').localeCompare(String(b.label ?? ''))
      })

      const bucketSpread = 1 + Math.min(singleLane ? 0.88 : 0.42, sortedNodes.length / 100)
      const waveY = singleLane ? Math.sin(yearRank * 0.52) * 260 + Math.cos(yearRank * 0.23) * 70 : 0
      const zigzagY = singleLane ? ((Math.round(yearRank) & 1) === 0 ? 95 : -95) : 0
      const baseY = laneY + waveY + zigzagY
      const xStretch = singleLane ? 0.78 : 0.88
      const yStretch = singleLane ? 3.4 : 1.08
      for (let idx = 0; idx < sortedNodes.length; idx += 1) {
        const node = sortedNodes[idx]
        const angle = baseAngle + idx * 2.399963229728653
        const radius = Math.sqrt(idx) * SPIRAL_STEP * bucketSpread
        const anchorX = baseX + Math.cos(angle) * radius * xStretch
        const anchorY = baseY + Math.sin(angle) * radius * yStretch

        positionMap.set(node.id, { x: anchorX, y: anchorY, anchorX, anchorY })
        anchorMap.set(node.id, { x: anchorX, y: anchorY })
      }
    }
  }

  relaxBuckets(positionMap, bucketNodeIds)
  applyRelationRelaxation(positionMap, anchorMap, bucketByNode, bucketNodeIds, edges)
  relaxBuckets(positionMap, bucketNodeIds)

  const positions = new Map<string, { x: number; y: number }>()
  for (const [id, pos] of positionMap.entries()) {
    positions.set(id, { x: pos.x, y: pos.y })
  }

  return {
    positions,
    meta: {
      yearAnchors,
      yearAxis,
      laneSummary,
    },
  }
}

function buildMiniMapSnapshot(cy: cytoscape.Core): MiniMapSnapshot | null {
  const nodes = cy.nodes(':visible').filter((n) => Number(n.data('__decorative') ?? 0) !== 1)
  if (!nodes.length) return null

  const bb = nodes.boundingBox({
    includeLabels: false,
    includeMainLabels: false,
    includeOverlays: false,
  })
  const w = Math.max(1, bb.w)
  const h = Math.max(1, bb.h)
  const extent = cy.extent()

  const points = nodes
    .toArray()
    .slice(0, 900)
    .map((n) => {
      if (!n.isNode()) return null
      const node = n as unknown as cytoscape.NodeSingular
      const pos = node.position()
      const size = clamp(Number(node.data('size') ?? 12) / 18, 1, 4.5)
      return {
        x: clamp((pos.x - bb.x1) / w, 0, 1),
        y: clamp((pos.y - bb.y1) / h, 0, 1),
        color: String(node.data('color') ?? 'rgba(125,211,252,0.9)'),
        size,
      }
    })
    .filter((item): item is { x: number; y: number; color: string; size: number } => item !== null)

  return {
    nodes: points,
    bounds: { x1: bb.x1, y1: bb.y1, w, h },
    viewport: {
      x: clamp((extent.x1 - bb.x1) / w, 0, 1),
      y: clamp((extent.y1 - bb.y1) / h, 0, 1),
      w: clamp((extent.x2 - extent.x1) / w, 0.02, 1),
      h: clamp((extent.y2 - extent.y1) / h, 0.02, 1),
    },
  }
}

export default function GraphCanvas({
  elements,
  layout,
  layoutTrigger,
  overviewMode,
  onOverviewModeChange,
  transitioning,
  onSelectNode,
}: Props) {
  const { state } = useGlobalState()
  const { locale, t } = useI18n()
  const { activeModule, selectedNode, graphUpdateReason } = state
  const [hiddenKinds, setHiddenKinds] = useState<string[]>([])
  const [placementMode, setPlacementMode] = useState<PlacementMode>('timeline')
  const [showGraphDetails, setShowGraphDetails] = useState(false)
  const [miniMap, setMiniMap] = useState<MiniMapSnapshot | null>(null)
  const [timelineViewport, setTimelineViewport] = useState<TimelineViewport | null>(null)
  const [cyReadyToken, setCyReadyToken] = useState(0)

  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const onSelectNodeRef = useRef(onSelectNode)
  const miniMapDragRef = useRef(false)

  useEffect(() => {
    onSelectNodeRef.current = onSelectNode
  }, [onSelectNode])

  const graphCanvasViewState = resolveGraphCanvasViewState({
    activeModule,
    overviewMode,
    placementMode,
    showGraphDetails,
  })
  const effectivePlacementMode = graphCanvasViewState.placementMode
  const { show3D, show2D } = graphCanvasViewState

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setHiddenKinds([])
    }, 0)
    return () => window.clearTimeout(timer)
  }, [activeModule, overviewMode])

  useEffect(() => {
    if (effectivePlacementMode !== 'timeline') {
      const timer = window.setTimeout(() => setTimelineViewport(null), 0)
      return () => window.clearTimeout(timer)
    }
  }, [effectivePlacementMode])

  const availableKinds = useMemo(() => {
    const set = new Set<string>()
    for (const el of elements) {
      if (el.group !== 'nodes') continue
      set.add(String((el.data as GraphNodeData).kind ?? 'unknown'))
    }
    return Array.from(set).sort((a, b) => {
      const diff = kindOrder(a) - kindOrder(b)
      if (diff !== 0) return diff
      return a.localeCompare(b)
    })
  }, [elements])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setHiddenKinds((prev) => prev.filter((kind) => availableKinds.includes(kind)))
    }, 0)
    return () => window.clearTimeout(timer)
  }, [availableKinds])

  useEffect(() => {
    if (!selectedNode) return
    if (hiddenKinds.includes(String(selectedNode.kind ?? ''))) {
      onSelectNodeRef.current(null)
    }
  }, [hiddenKinds, selectedNode])

  const filteredElements = useMemo(() => {
    if (!hiddenKinds.length) return elements

    const hidden = new Set(hiddenKinds)
    const visibleNodes = elements.filter((el) => {
      if (el.group !== 'nodes') return false
      return !hidden.has(String((el.data as GraphNodeData).kind ?? 'unknown'))
    })
    const visibleNodeIds = new Set(visibleNodes.map((el) => el.data.id))
    const visibleEdges = elements.filter((el) => {
      if (el.group !== 'edges') return false
      const edge = el.data as GraphEdgeData
      return visibleNodeIds.has(String(edge.source ?? '')) && visibleNodeIds.has(String(edge.target ?? ''))
    })
    return [...visibleNodes, ...visibleEdges]
  }, [elements, hiddenKinds])

  useEffect(() => {
    if (!hiddenKinds.length) return
    const hasVisibleNodes = filteredElements.some((el) => el.group === 'nodes')
    if (!hasVisibleNodes) {
      const timer = window.setTimeout(() => setHiddenKinds([]), 0)
      return () => window.clearTimeout(timer)
    }
  }, [filteredElements, hiddenKinds])

  // Avoid full graph re-layout on node selection in non-overview modules.
  // Selection highlight is handled by a separate effect.
  const selectedBackboneId =
    effectivePlacementMode === 'timeline' && activeModule === 'overview' && selectedNode
      ? String(selectedNode.id)
      : undefined

  const preparedGraph = useMemo((): PreparedGraph => {
    const nodeElements = filteredElements.filter((el) => el.group === 'nodes').map((el) => el.data as GraphNodeData)
    const rawEdges = filteredElements.filter((el) => el.group === 'edges').map((el) => ({ ...(el.data as GraphEdgeData) } satisfies InternalEdge))
    const nodeMap = new Map(nodeElements.map((n) => [n.id, n]))

    const degreeMap = new Map<string, number>()
    for (const edge of rawEdges) {
      degreeMap.set(String(edge.source ?? ''), (degreeMap.get(String(edge.source ?? '')) ?? 0) + 1)
      degreeMap.set(String(edge.target ?? ''), (degreeMap.get(String(edge.target ?? '')) ?? 0) + 1)
    }

    const dedup = new Map<string, InternalEdge>()
    for (const edge of rawEdges) {
      const key = `${edge.source}|${edge.target}|${edge.kind}`
      const existing = dedup.get(key)
      if (!existing) {
        dedup.set(key, {
          ...edge,
          aggregateCount: 1,
          weight: Number(edge.weight ?? 0),
          totalMentions: Number(edge.totalMentions ?? 0),
        })
        continue
      }
      existing.aggregateCount = Number(existing.aggregateCount ?? 1) + 1
      existing.weight = Number(existing.weight ?? 0) + Number(edge.weight ?? 0)
      existing.totalMentions = Number(existing.totalMentions ?? 0) + Number(edge.totalMentions ?? 0)
      if ((edge.purposeLabels ?? []).length) {
        const merged = new Set([...(existing.purposeLabels ?? []), ...(edge.purposeLabels ?? [])])
        existing.purposeLabels = Array.from(merged)
      }
    }
    const dedupEdges = Array.from(dedup.values()).map((edge) => ({
      ...edge,
      id: String(edge.id || `agg:${edge.source}->${edge.target}:${edge.kind}`),
      weight: Number(edge.weight ?? 0) / Math.max(1, Number(edge.aggregateCount ?? 1)),
    }))

    let edgesForRender: InternalEdge[] = rawEdges
    if (effectivePlacementMode === 'timeline') {
      edgesForRender = buildAggregateBackboneEdges(
        dedupEdges,
        nodeMap,
        nodeElements,
        degreeMap,
        selectedBackboneId,
      )
    }

    const unknownLabel = t('未知', 'Unknown')
    const meshLaneLabel = t('网状力导向', 'Force-directed Mesh')
    const getKindLabel = (kind: string) => kindLabel(kind, locale)
    const layoutPack =
      effectivePlacementMode === 'timeline'
        ? buildCockpitLayout(nodeElements, edgesForRender, degreeMap, unknownLabel, getKindLabel)
        : buildRawMeshLayout(nodeElements, edgesForRender, meshLaneLabel)
    const decorations =
      effectivePlacementMode === 'timeline' ? buildCockpitDecorations(nodeElements, layoutPack.positions, unknownLabel) : []

    const transformedNodes: PositionedElement[] = nodeElements.map((data) => {
      const degree = degreeMap.get(data.id) ?? 0
      const visual = nodeVisual(data, degree)
      return {
        group: 'nodes',
        data: {
          ...data,
          degree,
          size: visual.size,
          color: visual.color,
          borderColor: visual.borderColor,
          shape: visual.shape,
          shortLabel: shortLabel(data.shortLabel ?? data.label),
        },
        position: layoutPack.positions.get(data.id),
      }
    })

    const transformedEdges: PositionedElement[] = edgesForRender.map((data) => {
      const aggregateCount = Number(data.aggregateCount ?? 1)
      const visual = edgeVisual(String(data.kind ?? 'relates_to'), Number(data.weight ?? 0.5))
      return {
        group: 'edges',
        data: {
          ...data,
          id: String(data.id),
          edgeColor: visual.color,
          lineStyle: visual.lineStyle,
          arrow: visual.arrow,
          width:
            effectivePlacementMode === 'timeline'
              ? clamp(visual.width * 0.72 + Math.log2(aggregateCount + 1) * 0.4, 0.8, 3.6)
              : clamp(visual.width * 0.86, 0.84, 3.8),
          edgeOpacity:
            effectivePlacementMode === 'timeline'
              ? clamp(visual.opacity * 0.36 + Math.log2(aggregateCount + 1) * 0.04, 0.14, 0.62)
              : clamp(visual.opacity * 0.52, 0.16, 0.65),
          aggregateCount,
        },
      }
    })

    return {
      elements: [...decorations, ...transformedNodes, ...transformedEdges],
      rawEdgeCount: rawEdges.length,
      renderedEdgeCount: transformedEdges.length,
      layoutMeta: layoutPack.meta,
    }
  }, [effectivePlacementMode, filteredElements, locale, selectedBackboneId, t])

  useEffect(() => {
    if (!containerRef.current) return
    if (cyRef.current) return

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: buildStyle(),
      layout: { name: 'preset', fit: true, padding: 48 } as cytoscape.LayoutOptions,
      minZoom: 0.16,
      maxZoom: 3.4,
    })

    cy.on('tap', 'node', (evt) => {
      const node = evt.target as cytoscape.NodeSingular
      const data = node.data() as GraphNodeData & { __decorative?: number }
      if (Number(data.__decorative ?? 0) === 1) return

      const rawEvent = evt.originalEvent as MouseEvent | undefined
      const multiPick = Boolean(rawEvent?.ctrlKey || rawEvent?.metaKey || rawEvent?.shiftKey)
      if (multiPick) {
        const paperId = paperRefForAskScope(data)
        if (paperId) {
          const scope = loadScope()
          const existing = scope.mode === 'papers' ? scope.paperIds ?? [] : []
          const next = Array.from(new Set([...existing.map(String).filter(Boolean), paperId]))
          saveScope({ mode: 'papers', paperIds: next })
        }
      }

      cy.elements().addClass('faded')
      node.closedNeighborhood().removeClass('faded')
      cy.nodes().unselect()
      node.select()

      onSelectNodeRef.current({
        id: data.id,
        kind: data.kind,
        label: data.label,
        description: data.description,
        paperId: data.paperId,
        textbookId: data.textbookId,
        chapterId: data.chapterId,
        propId: data.propId,
      })
    })

    cy.on('tap', (evt) => {
      if (evt.target !== cy) return
      cy.elements().removeClass('faded')
      cy.nodes().unselect()
      onSelectNodeRef.current(null)
    })

    if (import.meta.env.DEV) {
      ;(window as Window & { __cy?: cytoscape.Core }).__cy = cy
    }

    cyRef.current = cy
    const readyTimer = window.setTimeout(() => setCyReadyToken((prev) => prev + 1), 0)

    return () => {
      window.clearTimeout(readyTimer)
      cyRef.current = null
      cy.destroy()
    }
  }, [])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.style(buildStyle())
    cy.style().update()
  }, [effectivePlacementMode])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    const renderPlan = resolveGraphRenderPlan(graphUpdateReason)
    const applyGraph = () => {
      syncGraphElements(cy, preparedGraph.elements)
      cy.elements().removeClass('faded')
      cy.nodes().unselect()
      cy
        .layout({
          name: 'preset',
          fit: true,
          padding: 64,
          animate: renderPlan.animate,
          animationDuration: renderPlan.animationDuration,
        } as cytoscape.LayoutOptions)
        .run()
    }

    if (renderPlan.fadeBeforeSwap) {
      cy.elements().addClass('faded')
    }

    if (renderPlan.delayMs > 0) {
      const timer = window.setTimeout(applyGraph, renderPlan.delayMs)
      return () => window.clearTimeout(timer)
    }

    applyGraph()
  }, [graphUpdateReason, layoutTrigger, preparedGraph])

  const selectedNodeId = selectedNode?.id ?? ''

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    if (!selectedNodeId) {
      cy.elements().removeClass('faded')
      cy.nodes().unselect()
      return
    }

    const node = cy.getElementById(selectedNodeId)
    if (!node.nonempty()) return
    cy.elements().addClass('faded')
    node.closedNeighborhood().removeClass('faded')
    cy.nodes().unselect()
    node.select()
  }, [selectedNodeId, preparedGraph.renderedEdgeCount])

  const visibleNodeCount = filteredElements.filter((el) => el.group === 'nodes').length

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    let rafId = 0
    const pump = () => {
      if (rafId) return
      rafId = window.requestAnimationFrame(() => {
        rafId = 0
        if (!show2D) {
          setMiniMap(null)
          return
        }
        setMiniMap(buildMiniMapSnapshot(cy))
      })
    }

    pump()
    const events = ['render', 'zoom', 'pan', 'resize', 'layoutstop', 'add', 'remove']
    for (const evt of events) cy.on(evt, pump)
    window.addEventListener('resize', pump)

    return () => {
      if (rafId) window.cancelAnimationFrame(rafId)
      for (const evt of events) cy.off(evt, pump)
      window.removeEventListener('resize', pump)
    }
  }, [show2D, preparedGraph.renderedEdgeCount])

  const timelineAxisTicks = useMemo(() => {
    if (effectivePlacementMode !== 'timeline') return []
    const axis = preparedGraph.layoutMeta.yearAxis
    if (!axis.length) return []
    const minX = axis.reduce((min, item) => Math.min(min, item.x), axis[0].x)
    const maxX = axis.reduce((max, item) => Math.max(max, item.x), axis[0].x)
    const span = Math.max(maxX - minX, 1)

    let sampled = [...axis].sort((a, b) => a.x - b.x)
    if (sampled.length > 14) {
      const step = Math.max(1, Math.floor(sampled.length / 12))
      const keep = new Set<number>([0, sampled.length - 1])
      for (let idx = step; idx < sampled.length - 1; idx += step) keep.add(idx)
      sampled.forEach((item, idx) => {
        if (item.key === 'unknown') keep.add(idx)
      })
      sampled = sampled.filter((_, idx) => keep.has(idx))
    }

    return sampled.map((item) => ({
      ...item,
      pct: clamp(((item.x - minX) / span) * 100, 0, 100),
    }))
  }, [effectivePlacementMode, preparedGraph.layoutMeta.yearAxis])

  useEffect(() => {
    if (!show2D || effectivePlacementMode !== 'timeline') {
      const timer = window.setTimeout(() => setTimelineViewport(null), 0)
      return () => window.clearTimeout(timer)
    }
    const cy = cyRef.current
    const axis = preparedGraph.layoutMeta.yearAxis
    if (!cy || !axis.length) {
      const timer = window.setTimeout(() => setTimelineViewport(null), 0)
      return () => window.clearTimeout(timer)
    }

    const minX = axis.reduce((min, item) => Math.min(min, item.x), axis[0].x)
    const maxX = axis.reduce((max, item) => Math.max(max, item.x), axis[0].x)
    const span = Math.max(maxX - minX, 1)

    let rafId = 0
    const pump = () => {
      if (rafId) return
      rafId = window.requestAnimationFrame(() => {
        rafId = 0
        const extent = cy.extent()
        const start = clamp((extent.x1 - minX) / span, 0, 1)
        const end = clamp((extent.x2 - minX) / span, 0, 1)
        const startLabel = nearestAxisLabel(extent.x1, axis)
        const endLabel = nearestAxisLabel(extent.x2, axis)
        const next: TimelineViewport = {
          start: Math.min(start, end),
          end: Math.max(start, end),
          startLabel,
          endLabel,
        }
        setTimelineViewport((prev) => {
          if (
            prev &&
            Math.abs(prev.start - next.start) < 0.004 &&
            Math.abs(prev.end - next.end) < 0.004 &&
            prev.startLabel === next.startLabel &&
            prev.endLabel === next.endLabel
          ) {
            return prev
          }
          return next
        })
      })
    }

    pump()
    const events = ['render', 'zoom', 'pan', 'resize', 'layoutstop']
    for (const evt of events) cy.on(evt, pump)
    window.addEventListener('resize', pump)

    return () => {
      if (rafId) window.cancelAnimationFrame(rafId)
      for (const evt of events) cy.off(evt, pump)
      window.removeEventListener('resize', pump)
    }
  }, [cyReadyToken, effectivePlacementMode, preparedGraph.layoutMeta.yearAxis, preparedGraph.renderedEdgeCount, show2D])

  function toggleKind(kind: string) {
    setHiddenKinds((prev) => {
      if (prev.includes(kind)) return prev.filter((item) => item !== kind)
      return [...prev, kind]
    })
  }

  function moveMiniMapViewport(clientX: number, clientY: number, box: HTMLDivElement) {
    const cy = cyRef.current
    if (!cy || !miniMap) return
    const rect = box.getBoundingClientRect()
    const x = clamp((clientX - rect.left) / Math.max(rect.width, 1), 0, 1)
    const y = clamp((clientY - rect.top) / Math.max(rect.height, 1), 0, 1)
    const targetX = miniMap.bounds.x1 + x * miniMap.bounds.w
    const targetY = miniMap.bounds.y1 + y * miniMap.bounds.h
    const zoom = cy.zoom()
    cy.animate({
      pan: {
        x: cy.width() / 2 - targetX * zoom,
        y: cy.height() / 2 - targetY * zoom,
      },
      duration: 180,
    })
  }

  const engineLabel = effectivePlacementMode === 'timeline' ? t('时序驾驶舱', 'Timeline Cockpit') : t('基础网状网络', 'Base Mesh Network')
  const layoutHint =
    effectivePlacementMode === 'timeline'
      ? t(`时间线布局（当前参数: ${layout}）`, `Timeline layout (active preset: ${layout})`)
      : t(`原始网状布局（当前参数: ${layout}）`, `Raw mesh layout (active preset: ${layout})`)
  const focusLabel = selectedNode ? shortLabel(String(selectedNode.label ?? selectedNode.id), 18) : ''

  return (
    <div className="kgCanvasSlot">
      <div className="kgGraphLegend">
        <div className="kgGraphLegendHead">
          <b>{t('语义驾驶舱', 'Semantic Cockpit')}</b>
          <div className="kgGraphLegendHeadMeta">
            <small>
              {visibleNodeCount}N | {preparedGraph.renderedEdgeCount}E
              {preparedGraph.renderedEdgeCount < preparedGraph.rawEdgeCount ? ` / ${preparedGraph.rawEdgeCount}` : ''}
            </small>
            {selectedNode && <span className="kgGraphFocusTag">{t('焦点', 'Focus')}: {focusLabel}</span>}
            <button
              className={`kgGraphMetaToggle${showGraphDetails ? ' is-active' : ''}`}
              type="button"
              onClick={() => setShowGraphDetails((prev) => !prev)}
            >
              {showGraphDetails ? t('收起', 'Collapse') : t('展开', 'Expand')}
            </button>
          </div>
        </div>

        <div className="kgGraphControlRow">
          <div className="kgGraphControlLabel">{t('排布', 'Layout')}</div>
          <div className="kgGraphControlGroup">
            {(Object.keys(PLACEMENT_MODE_LABELS) as PlacementMode[]).map((mode) => (
              <button
                key={mode}
                className={`kgGraphControlChip${effectivePlacementMode === mode ? ' is-active' : ''}`}
                type="button"
                onClick={() => {
                  if (activeModule !== 'overview') return
                  setPlacementMode(mode)
                }}
                title={
                  mode === 'timeline'
                    ? t('时间线布局（保持当前风格）', 'Timeline layout (preserve current visual style)')
                    : t('基础网状力导向布局', 'Base force-directed mesh layout')
                }
              >
                {pickText(locale, PLACEMENT_MODE_LABELS[mode])}
              </button>
            ))}
          </div>
        </div>

        {showGraphDetails && (
          <>
            <div className="kgGraphControlRow">
              <div className="kgGraphControlLabel">{t('布局', 'Engine')}</div>
              <div className="kgGraphControlGroup">
                <span className="kgGraphEngineBadge" title={layoutHint}>
                  {engineLabel}
                </span>
                <span className="kgGraphEngineMeta" title={layoutHint}>
                  {layoutHint}
                </span>
              </div>
            </div>

            {effectivePlacementMode === 'timeline' && (
              <>
                <div className="kgGraphControlRow">
                  <div className="kgGraphControlLabel">{t('分层', 'Lanes')}</div>
                  <div className="kgGraphControlGroup kgGraphLaneList">
                    {preparedGraph.layoutMeta.laneSummary.map((label) => (
                      <span key={label} className="kgGraphLaneChip">
                        {label}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="kgGraphControlRow">
                  <div className="kgGraphControlLabel">{t('时间', 'Years')}</div>
                  <div className="kgGraphControlGroup kgGraphYearList">
                    {preparedGraph.layoutMeta.yearAnchors.slice(0, 10).map((item) => (
                      <span key={item.key} className="kgGraphYearChip">
                        {item.label}
                      </span>
                    ))}
                    {preparedGraph.layoutMeta.yearAnchors.length > 10 && (
                      <span className="kgGraphYearChip">+{preparedGraph.layoutMeta.yearAnchors.length - 10}</span>
                    )}
                  </div>
                </div>
              </>
            )}

            <div className="kgGraphFilterList">
              {availableKinds.map((kind) => {
                const muted = hiddenKinds.includes(kind)
                return (
                  <button
                    key={kind}
                    className={`kgGraphFilterChip${muted ? ' is-muted' : ''}`}
                    type="button"
                    onClick={() => toggleKind(kind)}
                    title={`${muted ? t('显示', 'Show') : t('隐藏', 'Hide')} ${kindLabel(kind, locale)} ${t('节点', 'nodes')}`}
                  >
                    <span className="kgGraphFilterDot" style={{ background: colorOfKind(kind) }} />
                    <span>{kindLabel(kind, locale)}</span>
                  </button>
                )
              })}
            </div>
            {hiddenKinds.length > 0 && (
              <div className="kgGraphFilterReset">
                <button className="kgBtn kgBtn--sm" type="button" onClick={() => setHiddenKinds([])}>
                  {t('显示全部图层', 'Show All Layers')}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {show3D && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 10 }}>
          <Suspense
            fallback={(
              <div className="kgCanvasOverlay is-loading" style={{ position: 'absolute', inset: 0 }}>
                <div className="kgLoadingRing" />
              </div>
            )}
          >
            <Graph3D elements={filteredElements} onSelectNode={onSelectNode} transitioning={transitioning} />
          </Suspense>
        </div>
      )}
      <div ref={containerRef} className="kgGraphContainer" style={{ visibility: show2D ? 'visible' : 'hidden' }} />

      {show2D && miniMap && (
        <div className="kgMiniMapWrap">
          <div className="kgMiniMapHead">
            <span>{t('小地图', 'MiniMap')}</span>
            <small>{t('拖拽定位视窗', 'Drag to reposition viewport')}</small>
          </div>
          <div
            className="kgMiniMap"
            onMouseDown={(evt) => {
              miniMapDragRef.current = true
              moveMiniMapViewport(evt.clientX, evt.clientY, evt.currentTarget)
            }}
            onMouseMove={(evt) => {
              if (!miniMapDragRef.current) return
              moveMiniMapViewport(evt.clientX, evt.clientY, evt.currentTarget)
            }}
            onMouseUp={() => {
              miniMapDragRef.current = false
            }}
            onMouseLeave={() => {
              miniMapDragRef.current = false
            }}
          >
            {miniMap.nodes.map((node, idx) => (
              <span
                key={`${idx}-${node.x}-${node.y}`}
                className="kgMiniMapNode"
                style={{
                  left: `${node.x * 100}%`,
                  top: `${node.y * 100}%`,
                  width: `${node.size}px`,
                  height: `${node.size}px`,
                  background: node.color,
                }}
              />
            ))}
            <div
              className="kgMiniMapViewport"
              style={{
                left: `${miniMap.viewport.x * 100}%`,
                top: `${miniMap.viewport.y * 100}%`,
                width: `${miniMap.viewport.w * 100}%`,
                height: `${miniMap.viewport.h * 100}%`,
              }}
            />
          </div>
        </div>
      )}

      {show2D && effectivePlacementMode === 'timeline' && timelineAxisTicks.length > 0 && (
        <div className="kgTimelineAxisWrap">
          <div className="kgTimelineAxisHead">
            <span>{t('时间轴', 'Timeline Axis')}</span>
            <small>
              {timelineViewport
                ? t(
                    `可视区间 ${timelineViewport.startLabel} -> ${timelineViewport.endLabel}`,
                    `Visible range ${timelineViewport.startLabel} -> ${timelineViewport.endLabel}`,
                  )
                : t('时间轴', 'Timeline axis')}
            </small>
          </div>
          <div className="kgTimelineAxisTrack">
            {timelineViewport && (
              <span
                className="kgTimelineAxisWindow"
                style={{
                  left: `${timelineViewport.start * 100}%`,
                  width: `${Math.max(2, (timelineViewport.end - timelineViewport.start) * 100)}%`,
                }}
              />
            )}
            {timelineAxisTicks.map((tick) => (
              <span key={tick.key} className="kgTimelineAxisTick" style={{ left: `${tick.pct}%` }}>
                <span className="kgTimelineAxisTickDot" />
                <span className="kgTimelineAxisTickLabel">{tick.label}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className={`kgCanvasOverlay${transitioning ? ' is-loading' : ''}`}>
        <div className="kgLoadingRing" />
      </div>

      <div className="kgCanvasHud">
        {activeModule === 'overview' && (
          <div className="kgCanvasViewSwitch">
            <button
              className={`kgCanvasHudBtn${overviewMode === '3d' ? ' is-active' : ''}`}
              type="button"
              onClick={() => onOverviewModeChange('3d')}
            >
              3D
            </button>
            <button
              className={`kgCanvasHudBtn${overviewMode === '2d' ? ' is-active' : ''}`}
              type="button"
              onClick={() => onOverviewModeChange('2d')}
            >
              2D
            </button>
          </div>
        )}
        {show2D && (
          <>
            <button className="kgCanvasHudBtn" type="button" onClick={() => cyRef.current?.fit(undefined, 42)}>
              {t('适配', 'Fit')}
            </button>
            <button
              className="kgCanvasHudBtn"
              type="button"
              onClick={() => cyRef.current?.zoom(Math.min(3.4, (cyRef.current?.zoom() ?? 1) * 1.25))}
            >
              +
            </button>
            <button
              className="kgCanvasHudBtn"
              type="button"
              onClick={() => cyRef.current?.zoom(Math.max(0.16, (cyRef.current?.zoom() ?? 1) / 1.25))}
            >
              -
            </button>
          </>
        )}
      </div>
    </div>
  )
}
