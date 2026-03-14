import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'

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

describe('IngestPage manual community rebuild', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    window.localStorage.setItem(LOCALE_STORAGE_KEY, 'zh-CN')
    apiPostMock.mockImplementation(async (path: string) => {
      if (path === '/tasks/rebuild/community') return { task_id: 'task-community-1' }
      throw new Error(`unexpected apiPost path: ${path}`)
    })
  })

  test('submits a manual community rebuild task from the ingest center', async () => {
    render(
      <I18nProvider>
        <MemoryRouter initialEntries={['/ingest']}>
          <Routes>
            <Route path="/ingest" element={<IngestPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: '重建全局聚类' }))

    await waitFor(() => expect(apiPostMock).toHaveBeenCalledWith('/tasks/rebuild/community', {}))
    await waitFor(() => expect(screen.getByText('已提交任务：重建全局聚类（task-community-1）')).toBeInTheDocument())
  })
})
