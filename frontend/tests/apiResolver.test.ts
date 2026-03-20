import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

describe('api resolver', () => {
  const originalFetch = globalThis.fetch
  const originalWindow = globalThis.window
  const originalSessionStorage = globalThis.sessionStorage

  beforeEach(() => {
    vi.resetModules()
    vi.stubEnv('VITE_API_URL', '')

    const storage = new Map<string, string>()
    const sessionStorageMock = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, String(value))
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
      clear: () => {
        storage.clear()
      },
    }

    vi.stubGlobal('sessionStorage', sessionStorageMock)
    vi.stubGlobal('window', {
      location: { hostname: '127.0.0.1' },
      sessionStorage: sessionStorageMock,
    })

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/health')) {
        return new Response('', { status: 200 })
      }
      if (url.endsWith('/openapi.json')) {
        return new Response(
          JSON.stringify({
            paths: {
              '/graph/network': {},
              '/graph/papers': {},
              '/rag/ask_v2': {},
              '/textbooks': {},
            },
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        )
      }
      if (url.includes('/graph/papers?limit=1')) {
        return new Response(JSON.stringify({ papers: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as typeof fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.unstubAllEnvs()
    if (originalWindow === undefined) {
      vi.unstubAllGlobals()
    } else {
      vi.stubGlobal('window', originalWindow)
      if (originalSessionStorage !== undefined) vi.stubGlobal('sessionStorage', originalSessionStorage)
    }
    vi.restoreAllMocks()
  })

  test('reuses a verified api base url across repeated requests', async () => {
    const { apiGet } = await import('../src/api')

    await apiGet('/graph/papers?limit=1')
    await apiGet('/graph/papers?limit=1')

    const calls = vi.mocked(globalThis.fetch).mock.calls.map(([input]) => String(input))

    expect(calls.filter((url) => url.endsWith('/health'))).toHaveLength(0)
    expect(calls.filter((url) => url.endsWith('/openapi.json'))).toHaveLength(0)
    expect(calls.filter((url) => url.includes('/graph/papers?limit=1'))).toHaveLength(2)
    expect(calls).toEqual(['http://127.0.0.1:8000/graph/papers?limit=1', 'http://127.0.0.1:8000/graph/papers?limit=1'])
  })

  test('uses the configured api url exactly when VITE_API_URL is set', async () => {
    vi.stubEnv('VITE_API_URL', 'http://192.168.199.215:18000')

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === 'http://192.168.199.215:18000/graph/papers?limit=1') {
        return new Response(JSON.stringify({ papers: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as typeof fetch

    const { apiGet } = await import('../src/api')

    await apiGet('/graph/papers?limit=1')

    const calls = vi.mocked(globalThis.fetch).mock.calls.map(([input]) => String(input))

    expect(calls).toEqual(['http://192.168.199.215:18000/graph/papers?limit=1'])
  })

  test('ignores a stale stored api base and uses the current remote host backend', async () => {
    vi.stubGlobal('window', {
      location: { hostname: '192.168.199.215' },
      sessionStorage: globalThis.sessionStorage,
    })
    globalThis.sessionStorage.setItem('logickg.api.base', 'http://192.168.199.215:8000')

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === 'http://192.168.199.215:18000/graph/papers?limit=1') {
        return new Response(JSON.stringify({ papers: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as typeof fetch

    const { apiBaseUrl, apiGet } = await import('../src/api')

    await apiGet('/graph/papers?limit=1')
    const calls = vi.mocked(globalThis.fetch).mock.calls.map(([input]) => String(input))

    expect(apiBaseUrl()).toBe('http://192.168.199.215:18000')
    expect(globalThis.sessionStorage.getItem('logickg.api.base')).toBe('http://192.168.199.215:18000')
    expect(calls).toEqual(['http://192.168.199.215:18000/graph/papers?limit=1'])
  })

  test('does not fail over to another backend when the designated backend returns 404', async () => {
    vi.stubGlobal('window', {
      location: { hostname: '192.168.199.215' },
      sessionStorage: globalThis.sessionStorage,
    })

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === 'http://192.168.199.215:18000/community/overview-graph?community_limit=18&member_limit_per_community=6&max_nodes=160&max_edges=240') {
        return new Response('missing', { status: 404 })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as typeof fetch

    const { apiGet } = await import('../src/api')

    await expect(
      apiGet('/community/overview-graph?community_limit=18&member_limit_per_community=6&max_nodes=160&max_edges=240'),
    ).rejects.toThrow('missing')
    const calls = vi.mocked(globalThis.fetch).mock.calls.map(([input]) => String(input))

    expect(calls).toEqual(['http://192.168.199.215:18000/community/overview-graph?community_limit=18&member_limit_per_community=6&max_nodes=160&max_edges=240'])
  })
})
