type GraphDisplayBudgetOptions = {
  expandedCommunitySubgraph?: boolean
}

export function getModuleDisplayBudget(activeModule: string, options: GraphDisplayBudgetOptions = {}) {
  if (activeModule === 'overview' && options.expandedCommunitySubgraph) {
    return { maxNodes: 720, maxEdges: 960 }
  }
  if (activeModule === 'overview') {
    return { maxNodes: 360, maxEdges: 360 }
  }
  if (activeModule === 'papers') {
    return { maxNodes: 360, maxEdges: 360 }
  }
  if (activeModule === 'textbooks') {
    return { maxNodes: 220, maxEdges: 180 }
  }
  return { maxNodes: 240, maxEdges: 220 }
}
