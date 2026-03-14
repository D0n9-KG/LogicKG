import { beforeEach, describe, expect, test, vi } from 'vitest'

vi.mock('../src/api', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path === '/collections?limit=200') {
      return {
        collections: [{ collection_id: 'c1', name: 'Collection 1' }],
      }
    }

    if (path === '/graph/papers?limit=600') {
      return {
        papers: [{ paper_id: 'p1', paper_source: '14_1485', title: 'Paper One', collections: [] }],
      }
    }

    if (path === '/graph/papers?limit=600&collection_id=c1') {
      return {
        papers: [{ paper_id: 'p2', paper_source: '14_1486', title: 'Paper Two', collections: [] }],
      }
    }

    if (path === '/graph/papers?limit=1000') {
      return {
        papers: [{ paper_id: 'p1' }, { paper_id: 'p2' }],
      }
    }

    if (path === '/textbooks?limit=100') {
      return {
        textbooks: [{ textbook_id: 't1', title: 'Textbook', chapter_count: 10, entity_count: 80 }],
      }
    }

    throw new Error(`Unexpected path: ${path}`)
  }),
}))

import { apiGet } from '../src/api'
import {
  invalidatePanelDataCache,
  invalidatePaperDataCache,
  invalidateTextbookCatalogCache,
  loadOverviewStatsSnapshot,
  loadPaperCatalog,
  loadPaperCollections,
  loadTextbookCatalog,
} from '../src/loaders/panelData'

describe('panelData loader cache', () => {
  beforeEach(() => {
    invalidatePanelDataCache()
    vi.mocked(apiGet).mockClear()
  })

  test('caches overview stats between calls', async () => {
    const first = await loadOverviewStatsSnapshot()
    const second = await loadOverviewStatsSnapshot()

    expect(first.paperCount).toBe(2)
    expect(second).not.toHaveProperty('discoveryItems')
    expect(vi.mocked(apiGet)).toHaveBeenCalledTimes(1)
  })

  test('caches paper collections and catalog by filter key', async () => {
    await loadPaperCollections()
    await loadPaperCollections()
    await loadPaperCatalog('all')
    await loadPaperCatalog('all')
    await loadPaperCatalog('c1')

    expect(vi.mocked(apiGet)).toHaveBeenCalledTimes(3)
  })

  test('caches textbook catalog between calls', async () => {
    const first = await loadTextbookCatalog()
    const second = await loadTextbookCatalog()

    expect(first[0]?.textbook_id).toBe('t1')
    expect(second[0]?.entity_count).toBe(80)
    expect(vi.mocked(apiGet)).toHaveBeenCalledTimes(1)
  })

  test('refetches paper catalog after paper cache invalidation', async () => {
    await loadPaperCatalog('all')
    invalidatePaperDataCache()
    await loadPaperCatalog('all')

    expect(vi.mocked(apiGet)).toHaveBeenCalledTimes(2)
  })

  test('refetches textbook catalog after textbook cache invalidation', async () => {
    await loadTextbookCatalog()
    invalidateTextbookCatalogCache()
    await loadTextbookCatalog()

    expect(vi.mocked(apiGet)).toHaveBeenCalledTimes(2)
  })
})
