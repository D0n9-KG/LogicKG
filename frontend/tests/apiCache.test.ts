import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api resolution cache', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  test('reuses a validated API base without probing health and openapi again', async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = String(input)
      if (url.endsWith('/health')) return jsonResponse({ ok: true })
      if (url.endsWith('/openapi.json')) {
        return jsonResponse({
          paths: {
            '/graph/network': {},
            '/graph/papers': {},
            '/rag/ask_v2': {},
            '/textbooks': {},
          },
        })
      }
      if (url.endsWith('/graph/papers?limit=1')) return jsonResponse({ papers: [] })
      throw new Error(`Unexpected fetch URL: ${url}`)
    })

    vi.stubGlobal('fetch', fetchMock)

    const { apiGet } = await import('../src/api')

    await apiGet('/graph/papers?limit=1')
    await apiGet('/graph/papers?limit=1')

    const urls = fetchMock.mock.calls.map(([input]) => String(input))
    expect(urls.filter((url) => url.endsWith('/health'))).toHaveLength(1)
    expect(urls.filter((url) => url.endsWith('/openapi.json'))).toHaveLength(1)
    expect(urls.filter((url) => url.endsWith('/graph/papers?limit=1'))).toHaveLength(2)
  })
})
