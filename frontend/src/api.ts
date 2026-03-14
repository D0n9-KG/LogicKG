const API_URL = String((import.meta.env.VITE_API_URL as string | undefined) ?? '').trim().replace(/\/+$/, '')
const API_BASE_STORAGE_KEY = 'logickg.api.base'
const MAIN_WORKSPACE_BACKEND_PORTS = [8000, 8080, 18000, 8001, 8002]

function readStoredApiUrl() {
  if (typeof window === 'undefined' || typeof sessionStorage === 'undefined') return ''
  return String(sessionStorage.getItem(API_BASE_STORAGE_KEY) ?? '').trim().replace(/\/+$/, '')
}

function writeStoredApiUrl(baseUrl: string) {
  if (!baseUrl || typeof window === 'undefined' || typeof sessionStorage === 'undefined') return
  sessionStorage.setItem(API_BASE_STORAGE_KEY, baseUrl)
}

let resolvedApiUrl = readStoredApiUrl() || API_URL.replace(/\/+$/, '')
let resolveApiPromise: Promise<string> | null = null
let resolvedApiUrlVerified = false
const apiSurfaceCache = new Map<string, Set<string> | null>()
const apiUnsupportedPathCache = new Map<string, Set<string>>()

function uniq(values: string[]) {
  return Array.from(new Set(values.map((v) => String(v || '').trim().replace(/\/+$/, '')).filter(Boolean)))
}

function candidateUrlsForHost(host: string) {
  return MAIN_WORKSPACE_BACKEND_PORTS.map((port) => `http://${host}:${port}`)
}

function candidateApiUrls() {
  const staticCandidates = [...candidateUrlsForHost('127.0.0.1'), ...candidateUrlsForHost('localhost')]
  const stored = readStoredApiUrl()

  if (typeof window === 'undefined') return uniq([stored, resolvedApiUrl, API_URL, ...staticCandidates])

  const host = window.location.hostname || '127.0.0.1'
  const runtimeCandidates = candidateUrlsForHost(host)
  if (host === '127.0.0.1') runtimeCandidates.push(...candidateUrlsForHost('localhost'))
  if (host === 'localhost') runtimeCandidates.push(...candidateUrlsForHost('127.0.0.1'))

  return uniq([stored, resolvedApiUrl, API_URL, ...runtimeCandidates, ...staticCandidates])
}

const REQUIRED_API_PATHS = ['/graph/network', '/graph/papers', '/rag/ask_v2', '/textbooks']
const CRITICAL_API_PATH_PREFIXES = ['/graph/network', '/graph/papers', '/rag/ask_v2', '/textbooks', '/config-center', '/community']

function isCriticalApiPath(path: string) {
  return CRITICAL_API_PATH_PREFIXES.some((prefix) => path.startsWith(prefix))
}

function compatFallbackPath(path: string) {
  if (path.startsWith('/rag/ask_v2')) return path.replace('/rag/ask_v2', '/rag/ask')
  return null
}

function pathWithoutQuery(path: string) {
  return String(path || '').split('?')[0] || ''
}

function specPathCandidates(path: string) {
  const pathname = pathWithoutQuery(path)
  if (!pathname) return []
  if (/^\/textbooks\/[^/]+\/graph$/i.test(pathname)) return ['/textbooks/{textbook_id}/graph', pathname]
  if (/^\/textbooks\/[^/]+\/chapters\/[^/]+\/graph$/i.test(pathname)) {
    return ['/textbooks/{textbook_id}/chapters/{chapter_id}/graph', pathname]
  }
  return [pathname]
}

function isPathSupportedByCachedSurface(baseUrl: string, path: string): boolean | null {
  const normalizedCandidates = specPathCandidates(path)
  const unsupported = apiUnsupportedPathCache.get(baseUrl)
  if (unsupported && normalizedCandidates.some((candidate) => unsupported.has(candidate))) {
    return false
  }

  const surface = apiSurfaceCache.get(baseUrl)
  if (!surface) return null
  return normalizedCandidates.some((candidate) => surface.has(candidate))
}

function markPathUnsupported(baseUrl: string, path: string) {
  const normalizedCandidates = specPathCandidates(path)
  if (!normalizedCandidates.length) return
  const cache = apiUnsupportedPathCache.get(baseUrl) ?? new Set<string>()
  for (const candidate of normalizedCandidates) cache.add(candidate)
  apiUnsupportedPathCache.set(baseUrl, cache)
}

function rememberResolvedApiUrl(baseUrl: string) {
  resolvedApiUrl = baseUrl
  resolvedApiUrlVerified = true
  writeStoredApiUrl(baseUrl)
}

async function probeHealth(baseUrl: string) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 1200)
  try {
    const res = await fetch(`${baseUrl}/health`, { method: 'GET', signal: controller.signal })
    return res.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

async function probeApiSurface(baseUrl: string) {
  const healthy = await probeHealth(baseUrl)
  if (!healthy) return false

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 1800)
  try {
    const res = await fetch(`${baseUrl}/openapi.json`, { method: 'GET', signal: controller.signal })
    if (!res.ok) return true
    const spec = (await res.json()) as { paths?: Record<string, unknown> }
    const pathKeys = Object.keys(spec.paths ?? {})
    apiSurfaceCache.set(baseUrl, new Set(pathKeys))
    return REQUIRED_API_PATHS.every((p) => pathKeys.includes(p))
  } catch {
    // If OpenAPI probing fails, keep this candidate eligible based on health endpoint.
    apiSurfaceCache.set(baseUrl, null)
    return true
  } finally {
    clearTimeout(timer)
  }
}

async function resolveApiUrl() {
  if (resolvedApiUrlVerified) return resolvedApiUrl
  if (resolveApiPromise) return resolveApiPromise

  resolveApiPromise = (async () => {
    const candidates = candidateApiUrls()
    for (const baseUrl of candidates) {
      if (await probeApiSurface(baseUrl)) {
        resolvedApiUrl = baseUrl
        resolvedApiUrlVerified = true
        return baseUrl
      }
    }
    return resolvedApiUrl
  })()

  try {
    return await resolveApiPromise
  } finally {
    resolveApiPromise = null
  }
}

function isNetworkFailure(error: unknown) {
  if (error instanceof TypeError) return true
  const message = String((error as { message?: unknown } | null)?.message ?? error)
  return /failed to fetch|networkerror|network request failed/i.test(message)
}

async function fetchWithFailover(path: string, init?: RequestInit) {
  const primary = resolvedApiUrlVerified ? resolvedApiUrl : readStoredApiUrl() || await resolveApiUrl()
  const candidates = uniq([primary, ...candidateApiUrls()])

  let lastNetworkError: unknown = null
  for (const baseUrl of candidates) {
    const support = isPathSupportedByCachedSurface(baseUrl, path)
    if (support === false) continue
    try {
      const res = await fetch(`${baseUrl}${path}`, init)
      if (res.status === 404) {
        const fallbackPath = compatFallbackPath(path)
        if (fallbackPath) {
          const fallbackRes = await fetch(`${baseUrl}${fallbackPath}`, init)
          if (fallbackRes.status !== 404) {
            rememberResolvedApiUrl(baseUrl)
            return fallbackRes
          }
        }
        if (isCriticalApiPath(path)) {
          markPathUnsupported(baseUrl, path)
          continue
        }
      }
      rememberResolvedApiUrl(baseUrl)
      return res
    } catch (error: unknown) {
      if (!isNetworkFailure(error)) throw error
      if (baseUrl === resolvedApiUrl) {
        resolvedApiUrlVerified = false
      }
      lastNetworkError = error
    }
  }

  resolvedApiUrlVerified = false
  throw lastNetworkError ?? new Error('Failed to fetch API endpoint')
}

async function readJsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await res.text())
  return (await res.json()) as T
}

export async function apiGet<T>(path: string): Promise<T> {
  return readJsonOrThrow<T>(await fetchWithFailover(path))
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return readJsonOrThrow<T>(
    await fetchWithFailover(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return readJsonOrThrow<T>(
    await fetchWithFailover(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return readJsonOrThrow<T>(
    await fetchWithFailover(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function apiDelete<T>(path: string): Promise<T> {
  return readJsonOrThrow<T>(await fetchWithFailover(path, { method: 'DELETE' }))
}

export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  return readJsonOrThrow<T>(
    await fetchWithFailover(path, {
      method: 'POST',
      body: form,
    }),
  )
}

export function apiBaseUrl(): string {
  return resolvedApiUrl
}
