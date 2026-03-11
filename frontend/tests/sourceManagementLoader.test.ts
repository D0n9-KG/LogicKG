import { beforeEach, describe, expect, test, vi } from 'vitest'

const { mockApiGet, mockApiPost, mockLoadTextbookCatalog } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockApiPost: vi.fn(),
  mockLoadTextbookCatalog: vi.fn(),
}))

vi.mock('../src/api', () => ({
  apiGet: mockApiGet,
  apiPost: mockApiPost,
}))

vi.mock('../src/loaders/panelData', () => ({
  loadTextbookCatalog: mockLoadTextbookCatalog,
}))

import {
  loadDeleteTask,
  loadPaperManagementRows,
  loadTextbookManagementRows,
  submitPaperDeleteTask,
  submitTextbookDeleteTask,
} from '../src/loaders/sourceManagement'

describe('sourceManagement loaders', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('loads paper management rows through /papers/manage', async () => {
    mockApiGet.mockResolvedValue({
      papers: [{ paper_id: 'doi:10.1234/test', display_title: 'Attention Is All You Need' }],
    })

    const rows = await loadPaperManagementRows(50, 'attention')

    expect(rows[0]?.display_title).toBe('Attention Is All You Need')
    expect(mockApiGet).toHaveBeenCalledWith('/papers/manage?limit=50&q=attention')
  })

  test('submits paper and textbook delete tasks with rebuild enabled', async () => {
    mockApiPost.mockResolvedValue({ task_id: 'task-1' })

    const paperTask = await submitPaperDeleteTask(['p-1'])
    const textbookTask = await submitTextbookDeleteTask(['tb-1'])

    expect(paperTask.task_id).toBe('task-1')
    expect(textbookTask.task_id).toBe('task-1')
    expect(mockApiPost).toHaveBeenNthCalledWith(1, '/tasks/delete/papers', {
      paper_ids: ['p-1'],
      trigger_rebuild: true,
    })
    expect(mockApiPost).toHaveBeenNthCalledWith(2, '/tasks/delete/textbooks', {
      textbook_ids: ['tb-1'],
      trigger_rebuild: true,
    })
  })

  test('loads task records and forces textbook management refreshes', async () => {
    mockApiGet.mockResolvedValue({ task_id: 'task-2', status: 'running' })
    mockLoadTextbookCatalog.mockResolvedValue([{ textbook_id: 'tb-1', title: 'Deep Learning' }])

    const task = await loadDeleteTask('task-2')
    const textbooks = await loadTextbookManagementRows(25)

    expect(task.status).toBe('running')
    expect(mockApiGet).toHaveBeenCalledWith('/tasks/task-2')
    expect(mockLoadTextbookCatalog).toHaveBeenCalledWith(25, { force: true })
    expect(textbooks[0]?.title).toBe('Deep Learning')
  })
})
