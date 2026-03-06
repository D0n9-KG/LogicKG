const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

let resolvedApiUrl = API_URL.replace(/\/+$/, '')
let resolveApiPromise: Promise<string> | null = null

function uniq(values: string[]) {
  return Array.from(new Set(values.map((v) => String(v || '').trim().replace(/\/+$/, '')).filter(Boolean)))
}

function candidateApiUrls() {
  const staticCandidates = ['http://127.0.0.1:8000', 'http://127.0.0.1:8001', 'http://localhost:8000', 'http://localhost:8001']

  if (typeof window === 'undefined') return uniq([API_URL, ...staticCandidates])

  const host = window.location.hostname || '127.0.0.1'
  const runtimeCandidates = [`http://${host}:8000`, `http://${host}:8001`]
  if (host === '127.0.0.1') runtimeCandidates.push('http://localhost:8000', 'http://localhost:8001')
  if (host === 'localhost') runtimeCandidates.push('http://127.0.0.1:8000', 'http://127.0.0.1:8001')

  return uniq([API_URL, ...runtimeCandidates, ...staticCandidates])
}

const REQUIRED_API_PATHS = ['/graph/network', '/graph/papers', '/rag/ask_v2', '/textbooks']
const CRITICAL_API_PATH_PREFIXES = ['/graph/network', '/graph/papers', '/rag/ask_v2', '/textbooks', '/discovery', '/config-center']

function isCriticalApiPath(path: string) {
  return CRITICAL_API_PATH_PREFIXES.some((prefix) => path.startsWith(prefix))
}

function compatFallbackPath(path: string) {
  if (path.startsWith('/rag/ask_v2')) return path.replace('/rag/ask_v2', '/rag/ask')
  return null
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
    return REQUIRED_API_PATHS.every((p) => pathKeys.includes(p))
  } catch {
    // If OpenAPI probing fails, keep this candidate eligible based on health endpoint.
    return true
  } finally {
    clearTimeout(timer)
  }
}

async function resolveApiUrl() {
  if (resolveApiPromise) return resolveApiPromise

  resolveApiPromise = (async () => {
    const candidates = candidateApiUrls()
    for (const baseUrl of candidates) {
      if (await probeApiSurface(baseUrl)) {
        resolvedApiUrl = baseUrl
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
  const primary = await resolveApiUrl()
  const candidates = uniq([primary, ...candidateApiUrls()])

  let lastNetworkError: unknown = null
  for (const baseUrl of candidates) {
    try {
      const res = await fetch(`${baseUrl}${path}`, init)
      if (res.status === 404) {
        const fallbackPath = compatFallbackPath(path)
        if (fallbackPath) {
          const fallbackRes = await fetch(`${baseUrl}${fallbackPath}`, init)
          if (fallbackRes.status !== 404) {
            resolvedApiUrl = baseUrl
            return fallbackRes
          }
        }
        if (isCriticalApiPath(path)) continue
      }
      resolvedApiUrl = baseUrl
      return res
    } catch (error: unknown) {
      if (!isNetworkFailure(error)) throw error
      lastNetworkError = error
    }
  }

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
