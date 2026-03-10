import type { GraphElement } from '../state/types'

const OVERVIEW_ENTRY_NODE_KINDS = new Set(['paper', 'textbook', 'chapter', 'entity', 'community'])

function isNode(element: GraphElement): element is Extract<GraphElement, { group: 'nodes' }> {
  return element.group === 'nodes'
}

function isEdge(element: GraphElement): element is Extract<GraphElement, { group: 'edges' }> {
  return element.group === 'edges'
}

export function derivePapersEntryGraph(elements: GraphElement[], selectedPaperId: string | null): GraphElement[] | null {
  if (selectedPaperId) return null
  if (!elements.length) return null

  const nodes = elements.filter(isNode)
  if (!nodes.length) return null

  const hasUnexpectedKinds = nodes.some((element) => !OVERVIEW_ENTRY_NODE_KINDS.has(String(element.data.kind ?? '').trim()))
  if (hasUnexpectedKinds) return null

  const paperNodeIds = new Set(
    nodes
      .filter((element) => String(element.data.kind ?? '').trim() === 'paper')
      .map((element) => element.data.id),
  )
  if (!paperNodeIds.size) return null

  const paperNodes = nodes.filter((element) => paperNodeIds.has(element.data.id))
  const paperEdges = elements.filter(isEdge).filter((element) => {
    if (String(element.data.kind ?? '').trim() !== 'cites') return false
    return paperNodeIds.has(String(element.data.source ?? '')) && paperNodeIds.has(String(element.data.target ?? ''))
  })

  if (paperNodes.length === nodes.length && paperEdges.length === elements.filter(isEdge).length) {
    return elements
  }

  return [...paperNodes, ...paperEdges]
}

export function shouldHydratePapersOverviewGraph(elements: GraphElement[], selectedPaperId: string | null): boolean {
  if (selectedPaperId) return false
  return derivePapersEntryGraph(elements, selectedPaperId) === null
}
