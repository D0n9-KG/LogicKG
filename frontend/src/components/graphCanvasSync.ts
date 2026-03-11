import type cytoscape from 'cytoscape'

export type GraphCanvasElementDefinition = cytoscape.ElementDefinition

type GraphSyncStats = {
  addedCount: number
  removedCount: number
  updatedCount: number
}

function normalizePosition(position: cytoscape.Position | undefined): cytoscape.Position | undefined {
  if (!position) return undefined
  return { x: Number(position.x ?? 0), y: Number(position.y ?? 0) }
}

function updateExistingElement(
  element: cytoscape.SingularElementReturnValue,
  next: GraphCanvasElementDefinition,
) {
  const nextData = { ...(next.data ?? {}) }
  element.data(nextData)
  if (!element.isNode()) return

  const nextPosition = normalizePosition(next.position)
  if (!nextPosition) return
  ;(element as cytoscape.NodeSingular).position(nextPosition)
}

export function syncGraphElements(
  cy: cytoscape.Core,
  nextElements: GraphCanvasElementDefinition[],
): GraphSyncStats {
  const nextById = new Map<string, GraphCanvasElementDefinition>()
  for (const element of nextElements) {
    const id = String(element.data?.id ?? '').trim()
    if (!id) continue
    nextById.set(id, element)
  }

  const staleElements = cy.elements().filter((element) => !nextById.has(element.id()))
  const additions: GraphCanvasElementDefinition[] = []
  const updates: Array<{ element: cytoscape.SingularElementReturnValue; next: GraphCanvasElementDefinition }> = []

  for (const [id, next] of nextById) {
    const existing = cy.getElementById(id)
    if (existing.nonempty()) {
      updates.push({ element: existing, next })
      continue
    }
    additions.push(next)
  }

  cy.batch(() => {
    if (staleElements.length) {
      cy.remove(staleElements)
    }

    for (const update of updates) {
      updateExistingElement(update.element, update.next)
    }

    if (additions.length) {
      cy.add(additions)
    }
  })

  return {
    addedCount: additions.length,
    removedCount: staleElements.length,
    updatedCount: updates.length,
  }
}
