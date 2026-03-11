import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'

const {
  mockUseGlobalState,
  mockUseI18n,
  mockLoadTextbookCatalog,
  mockLoadTextbookChapters,
  mockInvalidateTextbookCatalogCache,
  mockInvalidateOverviewStatsCache,
  mockInvalidateOverviewGraphCache,
  mockSubmitTextbookDeleteTask,
  mockLoadDeleteTask,
  mockBuildTextbookChapterOverviewGraph,
  mockLoadTextbookEntityGraph,
} = vi.hoisted(() => ({
  mockUseGlobalState: vi.fn(),
  mockUseI18n: vi.fn(),
  mockLoadTextbookCatalog: vi.fn(),
  mockLoadTextbookChapters: vi.fn(),
  mockInvalidateTextbookCatalogCache: vi.fn(),
  mockInvalidateOverviewStatsCache: vi.fn(),
  mockInvalidateOverviewGraphCache: vi.fn(),
  mockSubmitTextbookDeleteTask: vi.fn(),
  mockLoadDeleteTask: vi.fn(),
  mockBuildTextbookChapterOverviewGraph: vi.fn(),
  mockLoadTextbookEntityGraph: vi.fn(),
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
  loadTextbookCatalog: mockLoadTextbookCatalog,
  loadTextbookChapters: mockLoadTextbookChapters,
  invalidateTextbookCatalogCache: mockInvalidateTextbookCatalogCache,
  invalidateOverviewStatsCache: mockInvalidateOverviewStatsCache,
}))

vi.mock('../src/loaders/overview', () => ({
  invalidateOverviewGraphCache: mockInvalidateOverviewGraphCache,
  loadOverviewGraph: vi.fn().mockResolvedValue([]),
}))

vi.mock('../src/loaders/textbooks', () => ({
  buildTextbookChapterOverviewGraph: mockBuildTextbookChapterOverviewGraph,
  loadTextbookEntityGraph: mockLoadTextbookEntityGraph,
}))

vi.mock('../src/loaders/sourceManagement', () => ({
  submitTextbookDeleteTask: mockSubmitTextbookDeleteTask,
  loadDeleteTask: mockLoadDeleteTask,
}))

import TextbooksPanel from '../src/panels/TextbooksPanel'
import { INITIAL_STATE } from '../src/state/store'

function renderPanel(stateOverrides: Record<string, unknown> = {}) {
  const dispatch = vi.fn()
  mockUseGlobalState.mockReturnValue({
    state: {
      ...INITIAL_STATE,
      ...stateOverrides,
      textbooks: {
        ...INITIAL_STATE.textbooks,
        ...(stateOverrides.textbooks as object | undefined),
      },
    },
    dispatch,
  })
  return { dispatch, ...render(<TextbooksPanel />) }
}

describe('TextbooksPanel delete flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseI18n.mockReturnValue({
      locale: 'en-US',
      t: (_zh: string, en: string) => en,
    })
    mockLoadTextbookCatalog.mockResolvedValue([
      { textbook_id: 'tb-1', title: 'Deep Learning', chapter_count: 3, entity_count: 42 },
    ])
    mockLoadTextbookChapters.mockResolvedValue([{ chapter_id: 'ch-1', chapter_num: 1, title: 'Basics' }])
    mockBuildTextbookChapterOverviewGraph.mockReturnValue([])
    mockLoadTextbookEntityGraph.mockResolvedValue([])
    mockSubmitTextbookDeleteTask.mockResolvedValue({ task_id: 'task-textbook-1' })
    mockLoadDeleteTask.mockResolvedValue({
      status: 'succeeded',
      result: { deleted_count: 1, failed_count: 0, skipped_count: 0 },
    })
  })

  test('submits a delete task for the selected textbook', async () => {
    const user = userEvent.setup()
    renderPanel({ textbooks: { selectedTextbookId: 'tb-1', selectedChapterId: null } })

    await user.click(await screen.findByRole('button', { name: /delete/i }))
    await user.click(screen.getByRole('button', { name: /confirm delete/i }))

    expect(mockSubmitTextbookDeleteTask).toHaveBeenCalledWith(['tb-1'])
  })

  test('clears textbook and chapter selection after deleting the active textbook', async () => {
    const user = userEvent.setup()
    const { dispatch } = renderPanel({ textbooks: { selectedTextbookId: 'tb-1', selectedChapterId: 'ch-1' } })

    await user.click(await screen.findByRole('button', { name: /delete/i }))
    await user.click(screen.getByRole('button', { name: /confirm delete/i }))

    await waitFor(() => expect(dispatch).toHaveBeenCalledWith({ type: 'TEXTBOOKS_SELECT', textbookId: null, chapterId: null }))
  })
})
