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

const STORAGE_KEY = 'logickg.ingest.state.v1'

describe('IngestPage keep existing', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    window.localStorage.setItem(LOCALE_STORAGE_KEY, 'zh-CN')

    const initialScan = {
      upload_id: 'upload-1',
      mode: 'folder',
      doi_strategy: 'title_crossref',
      root: '/tmp/upload-1',
      units: [
        {
          unit_id: 'paperA/paper.md',
          unit_rel_dir: 'paperA',
          md_rel_path: 'paperA/paper.md',
          doi: '10.1000/a',
          title: 'Conflict Paper',
          year: 2024,
          paper_type: 'research',
          status: 'conflict',
          existing_paper_id: 'doi:10.1000/a',
        },
      ],
      errors: [],
    }

    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        chunkMB: 8,
        uploadId: 'upload-1',
        scan: initialScan,
        doiStrategy: 'title_crossref',
        taskId: '',
        doiByUnit: {},
        paperTypeByUnit: {},
      }),
    )

    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/ingest/upload/scan?upload_id=upload-1') return initialScan
      throw new Error(`unexpected apiGet path: ${path}`)
    })
    apiPostMock.mockImplementation(async (path: string) => {
      if (path === '/ingest/upload/keep_existing') {
        return {
          ...initialScan,
          units: [],
        }
      }
      throw new Error(`unexpected apiPost path: ${path}`)
    })
  })

  test('uses keep_existing response directly without refreshing the scan endpoint again', async () => {
    render(
      <I18nProvider>
        <MemoryRouter initialEntries={['/ingest']}>
          <Routes>
            <Route path="/ingest" element={<IngestPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('Conflict Paper')).toBeInTheDocument())
    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(1))
    apiGetMock.mockClear()

    fireEvent.click(screen.getByRole('button', { name: '保留现有' }))

    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith('/ingest/upload/keep_existing', { upload_id: 'upload-1', unit_id: 'paperA/paper.md' }))
    await waitFor(() => expect(screen.queryByText('Conflict Paper')).not.toBeInTheDocument())
    expect(apiGetMock).not.toHaveBeenCalled()
  })
})
