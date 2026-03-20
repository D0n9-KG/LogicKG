const API_URL = String((import.meta.env.VITE_API_URL as string | undefined) ?? '').trim().replace(/\/+$/, '')
const API_BASE_STORAGE_KEY = 'logickg.api.base'
const LOCAL_API_URL = 'http://127.0.0.1:8000'
const REMOTE_BACKEND_PORT = 18000

function readStoredApiUrl() {
  if (typeof window === 'undefined' || typeof sessionStorage === 'undefined') return ''
  return String(sessionStorage.getItem(API_BASE_STORAGE_KEY) ?? '').trim().replace(/\/+$/, '')
}

function writeStoredApiUrl(baseUrl: string) {
  if (!baseUrl || typeof window === 'undefined' || typeof sessionStorage === 'undefined') return
  sessionStorage.setItem(API_BASE_STORAGE_KEY, baseUrl)
}

function isLoopbackHost(host: string) {
  return host === '127.0.0.1' || host === 'localhost'
}

function configuredApiUrl() {
  if (API_URL) return API_URL
  if (typeof window === 'undefined') return readStoredApiUrl()

  const host = String(window.location.hostname || '').trim() || '127.0.0.1'
  if (isLoopbackHost(host)) return LOCAL_API_URL
  return `http://${host}:${REMOTE_BACKEND_PORT}`
}

let resolvedApiUrl = configuredApiUrl()
if (resolvedApiUrl) writeStoredApiUrl(resolvedApiUrl)

function rememberResolvedApiUrl(baseUrl: string) {
  resolvedApiUrl = baseUrl
  writeStoredApiUrl(baseUrl)
}

function resolveApiUrl() {
  const baseUrl = configuredApiUrl() || readStoredApiUrl() || resolvedApiUrl
  if (!baseUrl) throw new Error('Missing API base URL')
  rememberResolvedApiUrl(baseUrl)
  return baseUrl
}

function compatFallbackPath(path: string) {
  if (path.startsWith('/rag/ask_v2')) return path.replace('/rag/ask_v2', '/rag/ask')
  return null
}

async function fetchFromDesignatedApi(path: string, init?: RequestInit) {
  const baseUrl = resolveApiUrl()
  const res = await fetch(`${baseUrl}${path}`, init)
  if (res.status !== 404) return res

  const fallbackPath = compatFallbackPath(path)
  if (!fallbackPath) return res
  return fetch(`${baseUrl}${fallbackPath}`, init)
}

async function readJsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await res.text())
  return (await res.json()) as T
}

export async function apiGet<T>(path: string): Promise<T> {
  return readJsonOrThrow<T>(await fetchFromDesignatedApi(path))
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return readJsonOrThrow<T>(
    await fetchFromDesignatedApi(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return readJsonOrThrow<T>(
    await fetchFromDesignatedApi(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return readJsonOrThrow<T>(
    await fetchFromDesignatedApi(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function apiDelete<T>(path: string): Promise<T> {
  return readJsonOrThrow<T>(await fetchFromDesignatedApi(path, { method: 'DELETE' }))
}

export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  return readJsonOrThrow<T>(
    await fetchFromDesignatedApi(path, {
      method: 'POST',
      body: form,
    }),
  )
}

export function apiBaseUrl(): string {
  return resolveApiUrl()
}
