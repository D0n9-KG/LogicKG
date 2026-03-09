import { beforeEach, describe, expect, test, vi } from 'vitest'

const { apiGetMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
}))

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
}))

import {
  invalidateOverviewStatsCache,
  invalidatePaperDataCache,
  invalidateTextbookCatalogCache,
  loadOverviewStatsSnapshot,
  loadPaperCatalog,
  loadPaperCollections,
  loadTextbookCatalog,
} from '../src/loaders/panelData'

describe('workspaceData cache', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    invalidateOverviewStatsCache()
    invalidatePaperDataCache()
    invalidateTextbookCatalogCache()
  })

  test('caches repeated paper collections and paper list requests', async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/collections?limit=200') return { collections: [{ collection_id: 'alloy', name: 'Alloy' }] }
      if (path === '/graph/papers?limit=600') return { papers: [{ paper_id: 'p1', paper_source: 'P1' }] }
      throw new Error(`Unexpected path: ${path}`)
    })

    const collectionsA = await loadPaperCollections()
    const collectionsB = await loadPaperCollections()
    const papersA = await loadPaperCatalog('all')
    const papersB = await loadPaperCatalog('all')

    expect(collectionsA).toEqual(collectionsB)
    expect(papersA).toEqual(papersB)
    expect(apiGetMock).toHaveBeenCalledTimes(2)
  })

  test('forces a refresh when requested explicitly', async () => {
    let version = 0
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/graph/papers?limit=1000') return { papers: Array.from({ length: 2 + version }, (_, idx) => idx) }
      if (path === '/discovery/candidates') return { candidates: [{ candidate_id: `c-${version}` }] }
      throw new Error(`Unexpected path: ${path}`)
    })

    const first = await loadOverviewStatsSnapshot()
    version = 1
    const second = await loadOverviewStatsSnapshot()
    invalidateOverviewStatsCache()
    const third = await loadOverviewStatsSnapshot()

    expect(second).toEqual(first)
    expect(third.paperCount).toBe(3)
    expect(third.discoveryItems[0]?.candidate_id).toBe('c-1')
    expect(apiGetMock).toHaveBeenCalledTimes(4)
  })

  test('keeps textbook list cached between module entries', async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/textbooks?limit=100') {
        return { textbooks: [{ textbook_id: 'tb-1', title: 'Textbook 1', chapter_count: 3, entity_count: 12 }] }
      }
      throw new Error(`Unexpected path: ${path}`)
    })

    const first = await loadTextbookCatalog()
    const second = await loadTextbookCatalog()

    expect(first).toEqual(second)
    expect(apiGetMock).toHaveBeenCalledTimes(1)
  })
})
