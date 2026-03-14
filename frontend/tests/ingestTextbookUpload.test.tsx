import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { I18nProvider, LOCALE_STORAGE_KEY } from '../src/i18n'

const { apiGetMock, apiPostMock, apiPostFormMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
  apiPostFormMock: vi.fn(),
}))

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
  apiPost: apiPostMock,
  apiPostForm: apiPostFormMock,
}))

vi.mock('../src/pages/ImportedSourceManagement', () => ({
  default: () => <div>Imported Source Management</div>,
}))

import IngestPage from '../src/pages/IngestPage'

describe('IngestPage textbook upload', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    window.localStorage.setItem(LOCALE_STORAGE_KEY, 'zh-CN')

    const textbookScan = {
      upload_id: 'tb-upload-1',
      mode: 'folder',
      root: '/tmp/tb-upload-1',
      units: [
        {
          unit_id: 'books/book-a/main.md',
          unit_rel_dir: 'books/book-a',
          main_md_rel_path: 'books/book-a/main.md',
          title: '多相流基础',
          textbook_id: 'tb:book-a',
          asset_count: 3,
          status: 'ready',
        },
      ],
      errors: [],
    }

    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/textbooks/upload/scan?upload_id=tb-upload-1') return textbookScan
      if (path === '/tasks/task-textbook-1') return { task_id: 'task-textbook-1', status: 'queued', progress: 0 }
      throw new Error(`unexpected apiGet path: ${path}`)
    })

    apiPostMock.mockImplementation(async (path: string) => {
      if (path === '/textbooks/upload/skip') {
        return {
          ...textbookScan,
          units: [
            {
              ...textbookScan.units[0],
              status: 'skipped',
            },
          ],
        }
      }
      throw new Error(`unexpected apiPost path: ${path}`)
    })
  })

  test('renders detected textbook units and allows skip', async () => {
    const { container } = render(
      <I18nProvider>
        <MemoryRouter initialEntries={['/ingest']}>
          <Routes>
            <Route path="/ingest" element={<IngestPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    )

    const loadInput = container.querySelector('input[name="textbook_load_upload_id"]') as HTMLInputElement | null
    expect(loadInput).toBeTruthy()
    fireEvent.change(loadInput!, { target: { value: 'tb-upload-1' } })
    fireEvent.click(screen.getByRole('button', { name: '载入教材会话' }))

    await waitFor(() => expect(screen.getByText('多相流基础')).toBeInTheDocument())
    expect(screen.getByText('教材导入')).toBeInTheDocument()
    expect(screen.getByText('books/book-a/main.md')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '跳过' }))

    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith('/textbooks/upload/skip', {
        upload_id: 'tb-upload-1',
        unit_id: 'books/book-a/main.md',
      }),
    )
    await waitFor(() => expect(screen.getByText('已跳过')).toBeInTheDocument())
  })
})
