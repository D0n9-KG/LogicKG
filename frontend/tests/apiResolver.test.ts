import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

describe('api resolver', () => {
  const originalFetch = globalThis.fetch
  const originalWindow = globalThis.window
  const originalSessionStorage = globalThis.sessionStorage

  beforeEach(() => {
    vi.resetModules()

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

    expect(calls.filter((url) => url.endsWith('/health'))).toHaveLength(1)
    expect(calls.filter((url) => url.endsWith('/openapi.json'))).toHaveLength(1)
    expect(calls.filter((url) => url.includes('/graph/papers?limit=1'))).toHaveLength(2)
  })

  test('prefers a previously successful api base from session storage before probing defaults', async () => {
    globalThis.sessionStorage.setItem('logickg.api.base', 'http://127.0.0.1:8001')

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === 'http://127.0.0.1:8001/graph/papers?limit=1') {
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

    expect(calls).toEqual(['http://127.0.0.1:8001/graph/papers?limit=1'])
  })

  test('skips a base whose openapi surface does not support textbook graph routes', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === 'http://127.0.0.1:8000/health') return new Response('', { status: 200 })
      if (url === 'http://127.0.0.1:8000/openapi.json') {
        return new Response(
          JSON.stringify({
            paths: {
              '/graph/network': {},
              '/graph/papers': {},
              '/rag/ask_v2': {},
              '/textbooks': {},
            },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (url === 'http://127.0.0.1:8000/graph/papers?limit=1') {
        return new Response(JSON.stringify({ papers: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url === 'http://127.0.0.1:8001/textbooks/tb-1/graph?entity_limit=260&edge_limit=520') {
        return new Response(JSON.stringify({ scope: 'textbook', textbook: { textbook_id: 'tb-1', title: 'TB' } }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as typeof fetch

    const { apiGet } = await import('../src/api')

    await apiGet('/graph/papers?limit=1')
    await apiGet('/textbooks/tb-1/graph?entity_limit=260&edge_limit=520')

    const calls = vi.mocked(globalThis.fetch).mock.calls.map(([input]) => String(input))

    expect(calls).not.toContain('http://127.0.0.1:8000/textbooks/tb-1/graph?entity_limit=260&edge_limit=520')
    expect(calls).toContain('http://127.0.0.1:8001/textbooks/tb-1/graph?entity_limit=260&edge_limit=520')
  })
})
