import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

describe('api resolver', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    vi.resetModules()

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
})
