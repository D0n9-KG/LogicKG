import { apiGet } from '../api'

export type OverviewStatsSnapshot = {
  paperCount: number
}

export type CollectionRow = {
  collection_id: string
  name: string
}

export type PaperRow = {
  paper_id: string
  paper_source: string
  title?: string
  year?: number
  ingested?: boolean
  collections?: CollectionRow[]
}

export type TextbookRow = {
  textbook_id: string
  title: string
  chapter_count: number
  entity_count: number
}

export type ChapterRow = {
  chapter_id: string
  chapter_num: number
  title: string
  entity_count?: number
  relation_count?: number
}

const responseCache = new Map<string, unknown>()
const pendingCache = new Map<string, Promise<unknown>>()

type LoadOptions = {
  force?: boolean
}

async function loadCached<T>(key: string, loader: () => Promise<T>, options: LoadOptions = {}): Promise<T> {
  if (options.force) {
    responseCache.delete(key)
    pendingCache.delete(key)
  }

  const cached = responseCache.get(key)
  if (cached !== undefined) return cached as T

  const pending = pendingCache.get(key)
  if (pending) return pending as Promise<T>

  const request = loader()
    .then((value) => {
      responseCache.set(key, value)
      return value
    })
    .finally(() => {
      pendingCache.delete(key)
    })

  pendingCache.set(key, request as Promise<unknown>)
  return request
}

function clearKeys(prefix: string) {
  for (const key of responseCache.keys()) {
    if (key.startsWith(prefix)) responseCache.delete(key)
  }
  for (const key of pendingCache.keys()) {
    if (key.startsWith(prefix)) pendingCache.delete(key)
  }
}

export function invalidatePanelDataCache() {
  responseCache.clear()
  pendingCache.clear()
}

export function invalidateOverviewStatsCache() {
  clearKeys('overview:')
}

export function invalidatePaperDataCache() {
  clearKeys('papers:')
}

export function invalidateTextbookCatalogCache() {
  clearKeys('textbooks:')
}

export async function loadOverviewStatsSnapshot(options: LoadOptions = {}): Promise<OverviewStatsSnapshot> {
  return loadCached(
    'overview:stats',
    async () => {
      const paperRes = await apiGet<{ papers: unknown[] }>('/graph/papers?limit=1000')
      return {
        paperCount: Array.isArray(paperRes.papers) ? paperRes.papers.length : 0,
      }
    },
    options,
  )
}

export async function loadPaperCollections(limit = 200, options: LoadOptions = {}): Promise<CollectionRow[]> {
  return loadCached(`papers:collections:${limit}`, async () => {
    const response = await apiGet<{ collections: CollectionRow[] }>(`/collections?limit=${limit}`)
    return response.collections ?? []
  }, options)
}

export async function loadPaperCatalog(collectionId = 'all', limit = 600, options: LoadOptions = {}): Promise<PaperRow[]> {
  return loadCached(`papers:list:${limit}:${collectionId}`, async () => {
    const cid = collectionId === 'all' ? '' : collectionId
    const qs = cid ? `&collection_id=${encodeURIComponent(cid)}` : ''
    const response = await apiGet<{ papers: PaperRow[] }>(`/graph/papers?limit=${limit}${qs}`)
    return response.papers ?? []
  }, options)
}

export async function loadTextbookCatalog(limit = 100, options: LoadOptions = {}): Promise<TextbookRow[]> {
  return loadCached(`textbooks:list:${limit}`, async () => {
    const response = await apiGet<{ textbooks: TextbookRow[] }>(`/textbooks?limit=${limit}`)
    return response.textbooks ?? []
  }, options)
}

export async function loadTextbookChapters(textbookId: string, options: LoadOptions = {}): Promise<ChapterRow[]> {
  return loadCached(`textbooks:chapters:${textbookId}`, async () => {
    const response = await apiGet<{ chapters: ChapterRow[] }>(`/textbooks/${encodeURIComponent(textbookId)}`)
    return response.chapters ?? []
  }, options)
}
