import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'

const { apiGetMock, apiPostMock, apiDeleteMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
  apiDeleteMock: vi.fn(),
}))

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
  apiPost: apiPostMock,
  apiDelete: apiDeleteMock,
}))

import SchemaPage from '../src/pages/SchemaPage'

describe('SchemaPage localization', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    apiPostMock.mockReset()
    apiDeleteMock.mockReset()

    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/schema/presets') {
        return {
          presets: [
            {
              id: 'balanced',
              label_zh: '均衡版',
              label_en: 'Balanced',
              summary_zh: '适合大多数批量抽取场景。',
            },
          ],
        }
      }

      if (path === '/schema/active?paper_type=research') {
        return {
          schema: {
            paper_type: 'research',
            version: 8,
            name: '均衡版',
            steps: [{ id: 'background', label_zh: '背景', label_en: 'Background', enabled: true, order: 1 }],
            claim_kinds: [{ id: 'definition', label_zh: '定义', label_en: 'Definition', enabled: true }],
            rules: {},
            prompts: {},
          },
        }
      }

      if (path === '/schema/versions?paper_type=research') {
        return {
          versions: [
            { version: 1, name: '默认版' },
            { version: 8, name: '均衡版' },
          ],
        }
      }

      throw new Error(`Unexpected path: ${path}`)
    })
  })

  test('uses Chinese chrome for schema management UI', async () => {
    render(
      <MemoryRouter initialEntries={['/schema']}>
        <Routes>
          <Route path="/schema" element={<SchemaPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('抽取规则（可配置）')).toBeInTheDocument())

    expect(screen.queryByText('Schema（可配置）')).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: '研究论文' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Research/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '规则' }))
    expect(screen.getByText('规则 JSON（高级，支持任意键）')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '提示词' }))
    expect(screen.getByText('提示词 JSON（高级，支持任意键）')).toBeInTheDocument()
  })
})
