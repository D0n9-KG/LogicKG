import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'

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

import { I18nProvider, LOCALE_STORAGE_KEY } from '../src/i18n'
import IngestPage from '../src/pages/IngestPage'

describe('IngestPage', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.localStorage.setItem(LOCALE_STORAGE_KEY, 'zh-CN')
    apiGetMock.mockReset()
    apiPostMock.mockReset()
    apiPostFormMock.mockReset()
    apiGetMock.mockResolvedValue({ units: [], errors: [] })
    apiPostMock.mockResolvedValue({})
    apiPostFormMock.mockResolvedValue({})
  })

  test('keeps upload controls visible after mounting imported source management', () => {
    const { container } = render(
      <I18nProvider>
        <MemoryRouter initialEntries={['/ingest']}>
          <Routes>
            <Route path="/ingest" element={<IngestPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    )

    expect(screen.getByText('论文导入')).toBeInTheDocument()
    expect(screen.getByText('教材导入')).toBeInTheDocument()
    expect(container.querySelector('input[name="ingest_zip_file"]')).toBeTruthy()
    expect(container.querySelector('input[name="ingest_folder_files"]')).toBeTruthy()
    expect(screen.getByText('Imported Source Management')).toBeInTheDocument()
  })

  test('defaults DOI strategy to title plus Crossref', () => {
    const { container } = render(
      <I18nProvider>
        <MemoryRouter initialEntries={['/ingest']}>
          <Routes>
            <Route path="/ingest" element={<IngestPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    )

    const select = container.querySelector('select[name="ingest_doi_strategy"]') as HTMLSelectElement | null
    expect(select).toBeTruthy()
    expect(select.value).toBe('title_crossref')
  })

  test('shows summary labels in Chinese by default', () => {
    render(
      <I18nProvider>
        <MemoryRouter initialEntries={['/ingest']}>
          <Routes>
            <Route path="/ingest" element={<IngestPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    )

    expect(screen.getByText('会话')).toBeInTheDocument()
    expect(screen.getByText('当前上传上下文')).toBeInTheDocument()
    expect(screen.queryByText('Session')).not.toBeInTheDocument()
    expect(screen.queryByText('Current upload context')).not.toBeInTheDocument()
  })

  test('shows compact task result summary and keeps raw JSON collapsed by default', async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/tasks/task-result-1') {
        return {
          task_id: 'task-result-1',
          type: 'ingest_upload_ready',
          status: 'succeeded',
          stage: 'done',
          message: 'Done',
          payload: {
            upload_id: 'upload-42',
          },
          result: {
            ok: true,
            ingested: 20,
            result: {
              run_id: '20260313104836',
              md_files: Array.from({ length: 20 }, (_, index) => `paper-${index + 1}.md`),
            },
          },
        }
      }
      if (path === '/ingest/upload/scan?upload_id=upload-42') {
        return {
          upload_id: 'upload-42',
          mode: 'folder',
          root: 'upload-42',
          units: [],
          errors: [],
        }
      }
      throw new Error(`Unexpected path: ${path}`)
    })

    render(
      <I18nProvider>
        <MemoryRouter initialEntries={['/ingest?task_id=task-result-1']}>
          <Routes>
            <Route path="/ingest" element={<IngestPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('任务结果')).toBeInTheDocument())

    expect(screen.getByText('已导入 20 篇')).toBeInTheDocument()
    expect(screen.getByText('Markdown 文件 20 个')).toBeInTheDocument()
    expect(screen.getAllByText('upload-42').length).toBeGreaterThan(0)
    expect(screen.queryByText('"md_files"')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '查看原始结果' }))
    await waitFor(() => expect(screen.getByText(/md_files/)).toBeInTheDocument())
  })
})
