import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'

const {
  mockUseGlobalState,
  mockUseI18n,
  mockLoadPaperCatalog,
  mockLoadPaperCollections,
  mockInvalidatePaperDataCache,
  mockInvalidateOverviewStatsCache,
  mockInvalidateOverviewGraphCache,
  mockLoadOverviewGraph,
  mockLoadPaperNeighborhood,
  mockSubmitPaperDeleteTask,
  mockLoadDeleteTask,
} = vi.hoisted(() => ({
  mockUseGlobalState: vi.fn(),
  mockUseI18n: vi.fn(),
  mockLoadPaperCatalog: vi.fn(),
  mockLoadPaperCollections: vi.fn(),
  mockInvalidatePaperDataCache: vi.fn(),
  mockInvalidateOverviewStatsCache: vi.fn(),
  mockInvalidateOverviewGraphCache: vi.fn(),
  mockLoadOverviewGraph: vi.fn(),
  mockLoadPaperNeighborhood: vi.fn(),
  mockSubmitPaperDeleteTask: vi.fn(),
  mockLoadDeleteTask: vi.fn(),
}))

vi.mock('../src/state/store', async () => {
  const actual = await vi.importActual<typeof import('../src/state/store')>('../src/state/store')
  return {
    ...actual,
    useGlobalState: mockUseGlobalState,
  }
})

vi.mock('../src/i18n', () => ({
  useI18n: mockUseI18n,
}))

vi.mock('../src/loaders/panelData', () => ({
  loadPaperCatalog: mockLoadPaperCatalog,
  loadPaperCollections: mockLoadPaperCollections,
  invalidatePaperDataCache: mockInvalidatePaperDataCache,
  invalidateOverviewStatsCache: mockInvalidateOverviewStatsCache,
}))

vi.mock('../src/loaders/overview', () => ({
  loadOverviewGraph: mockLoadOverviewGraph,
  invalidateOverviewGraphCache: mockInvalidateOverviewGraphCache,
}))

vi.mock('../src/loaders/papers', () => ({
  loadPaperNeighborhood: mockLoadPaperNeighborhood,
}))

vi.mock('../src/loaders/sourceManagement', () => ({
  submitPaperDeleteTask: mockSubmitPaperDeleteTask,
  loadDeleteTask: mockLoadDeleteTask,
}))

import PapersPanel from '../src/panels/PapersPanel'
import { INITIAL_STATE } from '../src/state/store'

function renderPanel(stateOverrides: Record<string, unknown> = {}) {
  const dispatch = vi.fn()
  mockUseGlobalState.mockReturnValue({
    state: {
      ...INITIAL_STATE,
      ...stateOverrides,
      papers: {
        ...INITIAL_STATE.papers,
        ...(stateOverrides.papers as object | undefined),
      },
    },
    dispatch,
    switchModule: vi.fn(),
  })
  return { dispatch, ...render(<PapersPanel />) }
}

describe('PapersPanel delete flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseI18n.mockReturnValue({
      locale: 'en-US',
      t: (_zh: string, en: string) => en,
    })
    mockLoadPaperCollections.mockResolvedValue([])
    mockLoadPaperCatalog.mockResolvedValue([
      {
        paper_id: 'doi:10.1234/test',
        paper_source: 'attention-source',
        title: 'Attention Is All You Need',
        ingested: true,
        year: 2017,
        collections: [],
      },
    ])
    mockLoadOverviewGraph.mockResolvedValue([])
    mockLoadPaperNeighborhood.mockResolvedValue([])
    mockSubmitPaperDeleteTask.mockResolvedValue({ task_id: 'task-paper-1' })
    mockLoadDeleteTask.mockResolvedValue({
      status: 'succeeded',
      result: { deleted_count: 1, failed_count: 0, skipped_count: 0 },
    })
  })

  test('submits a delete task for the selected paper', async () => {
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: /delete/i }))
    await user.click(screen.getByRole('button', { name: /confirm delete/i }))

    expect(mockSubmitPaperDeleteTask).toHaveBeenCalledWith(['doi:10.1234/test'])
  })

  test('clears the selected paper and restores overview graph after deleting the active paper', async () => {
    const user = userEvent.setup()
    const { dispatch } = renderPanel({
      activeModule: 'papers',
      papers: { selectedPaperId: 'doi:10.1234/test', searchQuery: '' },
    })

    await user.click(await screen.findByRole('button', { name: /delete/i }))
    await user.click(screen.getByRole('button', { name: /confirm delete/i }))

    await waitFor(() => expect(dispatch).toHaveBeenCalledWith({ type: 'PAPERS_SELECT', paperId: null }))
    expect(mockLoadOverviewGraph).toHaveBeenCalledWith(200, 600, { includeTextbooks: false })
  })
})
