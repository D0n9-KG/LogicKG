import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'

const {
  mockUseGlobalState,
  mockUseI18n,
  mockInvalidatePaperDataCache,
  mockInvalidateTextbookCatalogCache,
  mockInvalidateOverviewStatsCache,
  mockInvalidateOverviewGraphCache,
  mockLoadOverviewGraph,
  mockLoadPaperManagementRows,
  mockLoadTextbookManagementRows,
  mockSubmitPaperDeleteTask,
  mockSubmitTextbookDeleteTask,
  mockLoadDeleteTask,
} = vi.hoisted(() => ({
  mockUseGlobalState: vi.fn(),
  mockUseI18n: vi.fn(),
  mockInvalidatePaperDataCache: vi.fn(),
  mockInvalidateTextbookCatalogCache: vi.fn(),
  mockInvalidateOverviewStatsCache: vi.fn(),
  mockInvalidateOverviewGraphCache: vi.fn(),
  mockLoadOverviewGraph: vi.fn(),
  mockLoadPaperManagementRows: vi.fn(),
  mockLoadTextbookManagementRows: vi.fn(),
  mockSubmitPaperDeleteTask: vi.fn(),
  mockSubmitTextbookDeleteTask: vi.fn(),
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

vi.mock('../src/loaders/panelData', async () => {
  const actual = await vi.importActual<typeof import('../src/loaders/panelData')>('../src/loaders/panelData')
  return {
    ...actual,
    invalidatePaperDataCache: mockInvalidatePaperDataCache,
    invalidateTextbookCatalogCache: mockInvalidateTextbookCatalogCache,
    invalidateOverviewStatsCache: mockInvalidateOverviewStatsCache,
  }
})

vi.mock('../src/loaders/overview', () => ({
  invalidateOverviewGraphCache: mockInvalidateOverviewGraphCache,
  loadOverviewGraph: mockLoadOverviewGraph,
}))

vi.mock('../src/loaders/sourceManagement', async () => {
  const actual = await vi.importActual<typeof import('../src/loaders/sourceManagement')>('../src/loaders/sourceManagement')
  return {
    ...actual,
    loadPaperManagementRows: mockLoadPaperManagementRows,
    loadTextbookManagementRows: mockLoadTextbookManagementRows,
    submitPaperDeleteTask: mockSubmitPaperDeleteTask,
    submitTextbookDeleteTask: mockSubmitTextbookDeleteTask,
    loadDeleteTask: mockLoadDeleteTask,
  }
})

import ImportedSourceManagement from '../src/pages/ImportedSourceManagement'
import { INITIAL_STATE } from '../src/state/store'

function mockLoadDeleteTaskSequence(sequence: Array<Record<string, unknown>>) {
  const last = sequence[sequence.length - 1] ?? { status: 'succeeded', result: { deleted_count: 0, failed_count: 0, skipped_count: 0 } }
  let index = 0
  mockLoadDeleteTask.mockImplementation(async () => {
    const current = sequence[index] ?? last
    if (index < sequence.length - 1) index += 1
    return current
  })
}

function renderManagement(stateOverrides: Record<string, unknown> = {}) {
  const dispatch = vi.fn()
  mockUseGlobalState.mockReturnValue({
    state: {
      ...INITIAL_STATE,
      ...stateOverrides,
      papers: {
        ...INITIAL_STATE.papers,
        ...(stateOverrides.papers as object | undefined),
      },
      textbooks: {
        ...INITIAL_STATE.textbooks,
        ...(stateOverrides.textbooks as object | undefined),
      },
    },
    dispatch,
  })
  return { dispatch, ...render(<ImportedSourceManagement />) }
}

describe('ImportedSourceManagement', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseI18n.mockReturnValue({
      locale: 'en-US',
      t: (_zh: string, en: string) => en,
    })
    mockLoadOverviewGraph.mockResolvedValue([])
    mockLoadPaperManagementRows.mockResolvedValue([
      {
        paper_id: 'doi:10.1234/attention',
        paper_source: 'attention-source',
        title: 'Attention Is All You Need',
        display_title: 'Attention Is All You Need',
        doi: '10.1234/attention',
        ingested: true,
        deletable: true,
        collections: [{ collection_id: 'c-1', name: 'Transformers' }],
      },
      {
        paper_id: 'doi:10.1234/stub',
        paper_source: 'metadata-source',
        title: 'Metadata Only Title',
        display_title: 'Metadata Only Title',
        doi: '10.1234/stub',
        ingested: false,
        deletable: false,
        collections: [],
      },
    ])
    mockLoadTextbookManagementRows.mockResolvedValue([
      { textbook_id: 'tb-1', title: 'Deep Learning', chapter_count: 3, entity_count: 42 },
    ])
    mockSubmitPaperDeleteTask.mockResolvedValue({ task_id: 'task-paper-1' })
    mockSubmitTextbookDeleteTask.mockResolvedValue({ task_id: 'task-textbook-1' })
    mockLoadDeleteTaskSequence([
      { status: 'succeeded', result: { deleted_count: 1, failed_count: 0, skipped_count: 0 } },
    ])
  })

  test('renders ingested and metadata-only paper groups with readable titles', async () => {
    renderManagement()

    expect(await screen.findByText(/ingested papers/i)).toBeInTheDocument()
    expect(screen.getAllByText(/metadata-only papers/i).length).toBeGreaterThan(0)
    expect(screen.getByText('Attention Is All You Need')).toBeInTheDocument()
    expect(screen.queryByText('Metadata Only Title')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /show metadata-only papers \(1\)/i })).toBeInTheDocument()
    expect(screen.getByText(/deletion unavailable in v1/i)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Attention Is All You Need/i })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /Metadata Only Title/i })).not.toBeInTheDocument()
  })

  test('expands metadata-only papers on demand', async () => {
    const user = userEvent.setup()
    renderManagement()

    await user.click(await screen.findByRole('button', { name: /show metadata-only papers \(1\)/i }))

    expect(screen.getByText('Metadata Only Title')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /hide metadata-only papers \(1\)/i })).toBeInTheDocument()
  })

  test('filters paper rows through the search input across both groups', async () => {
    const user = userEvent.setup()
    renderManagement()

    await user.type(await screen.findByPlaceholderText(/search papers/i), 'attention')

    expect(screen.getByText('Attention Is All You Need')).toBeInTheDocument()
    expect(screen.queryByText('Metadata Only Title')).not.toBeInTheDocument()
  })

  test('selects all currently visible ingested papers from the filtered list', async () => {
    const user = userEvent.setup()
    mockLoadPaperManagementRows.mockResolvedValue([
      {
        paper_id: 'doi:10.1234/attention',
        paper_source: 'attention-source',
        title: 'Attention Is All You Need',
        display_title: 'Attention Is All You Need',
        doi: '10.1234/attention',
        ingested: true,
        deletable: true,
        collections: [],
      },
      {
        paper_id: 'doi:10.1234/bert',
        paper_source: 'bert-source',
        title: 'BERT Pretraining',
        display_title: 'BERT Pretraining',
        doi: '10.1234/bert',
        ingested: true,
        deletable: true,
        collections: [],
      },
      {
        paper_id: 'doi:10.1234/stub',
        paper_source: 'metadata-source',
        title: 'Metadata Only Title',
        display_title: 'Metadata Only Title',
        doi: '10.1234/stub',
        ingested: false,
        deletable: false,
        collections: [],
      },
    ])

    renderManagement()

    await user.type(await screen.findByPlaceholderText(/search papers/i), 'attention')
    await user.click(screen.getByRole('checkbox', { name: /select all visible papers/i }))
    await user.click(screen.getByRole('button', { name: /delete selected papers/i }))

    expect(mockSubmitPaperDeleteTask).toHaveBeenCalledWith(['doi:10.1234/attention'])
  })

  test('selects all textbooks from the textbook management list', async () => {
    const user = userEvent.setup()
    mockLoadTextbookManagementRows.mockResolvedValue([
      { textbook_id: 'tb-1', title: 'Deep Learning', chapter_count: 3, entity_count: 42 },
      { textbook_id: 'tb-2', title: 'Pattern Recognition', chapter_count: 5, entity_count: 64 },
    ])

    renderManagement()

    const selectAll = await screen.findByRole('checkbox', { name: /select all textbooks/i })
    await user.click(selectAll)
    expect(selectAll).toBeChecked()

    await user.click(screen.getByRole('button', { name: /delete selected textbooks/i }))

    expect(mockSubmitTextbookDeleteTask).toHaveBeenCalledWith(['tb-1', 'tb-2'])
  })

  test('keeps textbook rows visible when paper management loading fails', async () => {
    mockLoadPaperManagementRows.mockRejectedValue(new Error('paper management failed'))

    renderManagement()

    expect(await screen.findByText('Deep Learning')).toBeInTheDocument()
    expect(screen.getByText('paper management failed')).toBeInTheDocument()
    expect(screen.getByText(/3 chapters/i)).toBeInTheDocument()
  })

  test('submits selected papers, shows summary, and clears the active paper selection when removed', async () => {
    const user = userEvent.setup()
    const { dispatch } = renderManagement({
      activeModule: 'papers',
      papers: { selectedPaperId: 'doi:10.1234/attention', searchQuery: '' },
    })

    await user.click(await screen.findByRole('checkbox', { name: /Attention Is All You Need/i }))
    await user.click(screen.getByRole('button', { name: /delete selected papers/i }))

    expect(mockSubmitPaperDeleteTask).toHaveBeenCalledWith(['doi:10.1234/attention'])
    await waitFor(() => expect(dispatch).toHaveBeenCalledWith({ type: 'PAPERS_SELECT', paperId: null }))
    expect(mockLoadOverviewGraph).toHaveBeenCalledWith(200, 600, { includeTextbooks: false })
    expect(await screen.findByText(/deleted: 1/i)).toBeInTheDocument()
  })

  test('submits selected textbooks and clears textbook selection after deletion', async () => {
    const user = userEvent.setup()
    const { dispatch } = renderManagement({
      activeModule: 'textbooks',
      textbooks: { selectedTextbookId: 'tb-1', selectedChapterId: 'ch-1' },
    })

    await user.click(await screen.findByRole('checkbox', { name: /Deep Learning/i }))
    await user.click(screen.getByRole('button', { name: /delete selected textbooks/i }))

    expect(mockSubmitTextbookDeleteTask).toHaveBeenCalledWith(['tb-1'])
    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith({ type: 'TEXTBOOKS_SELECT', textbookId: null, chapterId: null }),
    )
  })

  test('shows queued feedback immediately after submitting textbook deletion', async () => {
    const user = userEvent.setup()
    let resolveTask: ((value: Record<string, unknown>) => void) | null = null
    mockLoadDeleteTask.mockReturnValue(
      new Promise((resolve) => {
        resolveTask = resolve
      }),
    )

    renderManagement()

    await user.click(await screen.findByRole('checkbox', { name: /Deep Learning/i }))
    await user.click(screen.getByRole('button', { name: /delete selected textbooks/i }))

    expect(mockSubmitTextbookDeleteTask).toHaveBeenCalledWith(['tb-1'])
    expect(await screen.findByText(/delete task is queued/i)).toBeInTheDocument()

    await act(async () => {
      resolveTask?.({
        status: 'succeeded',
        result: { deleted_count: 1, failed_count: 0, skipped_count: 0 },
      })
    })

    expect(await screen.findByText(/deleted: 1/i)).toBeInTheDocument()
  })

  test('surfaces textbook deletion item failures even when task record succeeds', async () => {
    const user = userEvent.setup()
    mockLoadDeleteTaskSequence([
      {
        status: 'succeeded',
        result: {
          deleted_count: 0,
          failed_count: 1,
          skipped_count: 0,
          items: [{ id: 'tb-1', status: 'failed', reason: 'not_found' }],
        },
      },
    ])

    renderManagement()

    await user.click(await screen.findByRole('checkbox', { name: /Deep Learning/i }))
    await user.click(screen.getByRole('button', { name: /delete selected textbooks/i }))

    expect(await screen.findByText(/some selected textbooks could not be deleted: not_found/i)).toBeInTheDocument()
  })

  test('renders management copy in Chinese when locale is zh-CN', async () => {
    mockUseI18n.mockReturnValue({
      locale: 'zh-CN',
      t: (zh: string) => zh,
    })

    renderManagement()

    expect(await screen.findByText('已导入源管理')).toBeInTheDocument()
    expect(screen.getByText('论文管理')).toBeInTheDocument()
    expect(screen.getByText('仅元数据论文')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '展开仅元数据论文（1）' })).toBeInTheDocument()
    expect(screen.getByText('暂不支持删除，仅展示为只读元数据。')).toBeInTheDocument()
    expect(screen.getByText('教材管理')).toBeInTheDocument()
  })
})
