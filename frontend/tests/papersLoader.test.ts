import { beforeEach, describe, expect, test, vi } from 'vitest'

const { apiGetMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
}))

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
}))

import { loadPaperNeighborhood } from '../src/loaders/papers'

describe('papersLoader', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    apiGetMock.mockResolvedValue({
      nodes: [],
      edges: [],
      center_id: 'paper-1',
    })
  })

  test('uses the expanded paper neighborhood budget', async () => {
    await loadPaperNeighborhood('paper-1')

    expect(apiGetMock).toHaveBeenCalledWith('/graph/neighborhood?paper_id=paper-1&depth=1&limit_nodes=170&limit_edges=380')
  })
})
