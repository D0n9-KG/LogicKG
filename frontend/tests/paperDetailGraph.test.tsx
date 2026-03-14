import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'

import { I18nProvider, LOCALE_STORAGE_KEY } from '../src/i18n'

const { apiGetMock, apiPatchMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPatchMock: vi.fn(),
  apiPostMock: vi.fn(),
}))

vi.mock('../src/api', () => ({
  apiBaseUrl: () => 'http://127.0.0.1:8080',
  apiGet: apiGetMock,
  apiPatch: apiPatchMock,
  apiPost: apiPostMock,
}))

vi.mock('../src/components/MarkdownView', () => ({
  default: ({ markdown }: { markdown: string }) => <div>{markdown}</div>,
}))

vi.mock('../src/components/SignalGraph', () => ({
  default: ({
    nodes,
    onSelect,
  }: {
    nodes: Array<{ id: string; label: string }>
    onSelect?: (nodeId: string) => void
  }) => (
    <div data-testid="signal-graph-mock">
      {nodes.map((node) => (
        <button key={node.id} onClick={() => onSelect?.(node.id)}>
          {node.label}
        </button>
      ))}
    </div>
  ),
}))

import PaperDetailPage from '../src/pages/PaperDetailPage'

const scrollIntoViewMock = vi.fn()

function buildPaperDetail(citationCount = 12) {
  return {
    paper: {
      paper_id: 'doi:10.1000/example',
      doi: '10.1000/example',
      year: 2024,
      title: '颗粒混合研究',
      paper_source: 'paper-source',
      phase1_gate_passed: true,
      phase1_quality_tier: 'green',
      phase1_quality_tier_score: 1,
    },
    schema: {
      paper_type: 'research',
      version: 1,
      steps: [
        { id: 'Background', label_zh: '背景', label_en: 'Background', enabled: true, order: 0 },
        { id: 'Method', label_zh: '方法', label_en: 'Method', enabled: true, order: 1 },
        { id: 'Result', label_zh: '结果', label_en: 'Result', enabled: true, order: 2 },
      ],
      claim_kinds: [{ id: 'finding', label_zh: '发现', label_en: 'Finding', enabled: true }],
      rules: {},
    },
    stats: { chunk_count: 20, ref_count: citationCount },
    logic_steps: [
      { step_type: 'Background', summary: '背景摘要', confidence: 0.76, order: 0 },
      { step_type: 'Method', summary: '方法摘要', confidence: 0.8, order: 1 },
      { step_type: 'Result', summary: '结果摘要', confidence: 0.9, order: 2 },
    ],
    claims: [
      {
        claim_key: 'claim-bg-1',
        text: '背景观点一',
        confidence: 0.65,
        step_type: 'Background',
        kinds: ['finding'],
      },
      {
        claim_key: 'claim-method-1',
        text: '方法要点一',
        confidence: 0.83,
        step_type: 'Method',
        kinds: ['finding'],
      },
      {
        claim_key: 'claim-method-2',
        text: '方法要点二',
        confidence: 0.74,
        step_type: 'Method',
        kinds: ['finding'],
      },
      {
        claim_key: 'claim-result-1',
        text: '结论一',
        confidence: 0.92,
        step_type: 'Result',
        kinds: ['finding'],
      },
      {
        claim_key: 'claim-result-2',
        text: '结果观点二',
        confidence: 0.79,
        step_type: 'Result',
        kinds: ['finding'],
      },
    ],
    figures: [],
    outgoing_cites: Array.from({ length: citationCount }, (_, index) => ({
      cited_paper_id: `cite-${index + 1}`,
      cited_doi: `10.1000/cite-${index + 1}`,
      cited_title: `引用论文 ${index + 1}`,
      total_mentions: citationCount - index,
      ref_nums: [index + 1],
      purpose_labels: ['Background'],
      purpose_scores: [0.8],
      semantic: {
        polarity: index === 0 ? 'positive' : 'neutral',
        semantic_signals: index === 0 ? ['method_transfer_hint'] : [],
        target_scopes: index === 0 ? ['paper', 'method'] : ['paper'],
        evidence_chunk_ids: index === 0 ? ['chunk-2', 'chunk-4'] : [],
        evidence_spans: index === 0 ? ['20-22'] : [],
      },
      mentions: index === 0
        ? [
            {
              mention_id: 'mention-1',
              ref_num: 1,
              source_chunk_id: 'chunk-2',
              span_start: 20,
              span_end: 22,
              section: 'method',
              context_text: 'This method is adapted from the cited paper.',
            },
          ]
        : [],
    })),
    unresolved: [],
  }
}

function buildPaperDetailWithoutCitationEnrichment() {
  const detail = buildPaperDetail(3)
  return {
    ...detail,
    outgoing_cites: detail.outgoing_cites.map((cite, index) => {
      if (index !== 0) return cite
      const rest = { ...cite }
      delete rest.semantic
      delete rest.mentions
      return rest
    }),
  }
}

function renderPaperDetail(citationCount = 12) {
  apiGetMock.mockImplementation(async (path: string) => {
    if (path === '/graph/paper/doi%3A10.1000%2Fexample') return buildPaperDetail(citationCount)
    throw new Error(`unexpected apiGet path: ${path}`)
  })

  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/papers/doi%3A10.1000%2Fexample']}>
        <Routes>
          <Route path="/papers/:paperId" element={<PaperDetailPage />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
}

describe('PaperDetailPage graph workbench', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    scrollIntoViewMock.mockReset()
    Element.prototype.scrollIntoView = scrollIntoViewMock
    window.localStorage.clear()
    window.localStorage.setItem(LOCALE_STORAGE_KEY, 'zh-CN')
  })

  test('shows a detail card when a graph node is selected', async () => {
    const { container } = renderPaperDetail()

    await waitFor(() => expect(screen.getByTestId('signal-graph-mock')).toBeInTheDocument())
    expect(container.querySelector('.paperGraphWorkbench')).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '方法(Method)' }))

    const detailCard = container.querySelector('.paperGraphDetailCard')
    expect(detailCard).not.toBeNull()
    const detail = within(detailCard as HTMLElement)

    expect(detail.getByText('节点详情')).toBeInTheDocument()
    expect(detail.getByText('方法(Method)')).toBeInTheDocument()
    expect(detail.getByText('逻辑步骤')).toBeInTheDocument()
    expect(detail.getByText('方法摘要')).toBeInTheDocument()
  })

  test('renders all logic steps and claims without citation nodes', async () => {
    renderPaperDetail(12)

    await waitFor(() => expect(screen.getByTestId('signal-graph-mock')).toBeInTheDocument())

    expect(screen.getByRole('button', { name: '背景(Background)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '方法(Method)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '结果(Result)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发现(Finding) | 背景观点一' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发现(Finding) | 方法要点一' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发现(Finding) | 方法要点二' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发现(Finding) | 结论一' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发现(Finding) | 结果观点二' })).toBeInTheDocument()
    expect(screen.queryByText(/更多引用 \+\d+/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /引用论文/ })).not.toBeInTheDocument()
  })
  test('opens the matching claim card from the detail action without auto-switching on select', async () => {
    renderPaperDetail(12)

    await waitFor(() => expect(screen.getByTestId('signal-graph-mock')).toBeInTheDocument())

    const claimButtons = screen.getAllByRole('button').filter((button) => button.textContent?.includes('Finding'))
    fireEvent.click(claimButtons[1])

    expect(screen.queryByText('claim-method-1')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /完整论断/ }))

    await waitFor(() => expect(screen.getByText('claim-method-1')).toBeInTheDocument())
    await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalled())
  })

  test('renders citation semantic enrichment and keeps manual purpose controls collapsed by default', async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/graph/paper/doi%3A10.1000%2Fexample') return buildPaperDetail(12)
      throw new Error(`unexpected apiGet path: ${path}`)
    })

    render(
      <I18nProvider>
        <MemoryRouter initialEntries={['/papers/doi%3A10.1000%2Fexample?tab=cites']}>
          <Routes>
            <Route path="/papers/:paperId" element={<PaperDetailPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('引用论文 1')).toBeInTheDocument())

    const firstCitationCard = screen.getByText('引用论文 1').closest('.itemCard') as HTMLElement
    const citationCard = within(firstCitationCard)

    expect(citationCard.getByText('语义画像')).toBeInTheDocument()
    expect(citationCard.getByText('方法迁移提示')).toBeInTheDocument()
    expect(citationCard.getByText('方法')).toBeInTheDocument()
    expect(citationCard.getByText('引用依据')).toBeInTheDocument()
    expect(citationCard.getByText('背景')).toBeInTheDocument()
    expect(citationCard.getByText('置信度 0.80')).toBeInTheDocument()
    expect(citationCard.getByText('chunk-2')).toBeInTheDocument()
    expect(citationCard.getByRole('button', { name: /提及证据 1/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '综述' })).not.toBeInTheDocument()

    fireEvent.click(citationCard.getByRole('button', { name: /提及证据 1/ }))
    expect(screen.getByText('This method is adapted from the cited paper.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /人工校正引用目的/ }))
    expect(screen.getAllByRole('button', { name: '综述' }).length).toBeGreaterThan(0)
  })

  test('renders missing citation enrichment state clearly when semantic and mentions are absent', async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      if (path === '/graph/paper/doi%3A10.1000%2Fexample') return buildPaperDetailWithoutCitationEnrichment()
      throw new Error(`unexpected apiGet path: ${path}`)
    })

    render(
      <I18nProvider>
        <MemoryRouter initialEntries={['/papers/doi%3A10.1000%2Fexample?tab=cites']}>
          <Routes>
            <Route path="/papers/:paperId" element={<PaperDetailPage />} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('引用论文 1')).toBeInTheDocument())

    const firstCitationCard = screen.getByText('引用论文 1').closest('.itemCard') as HTMLElement
    const citationCard = within(firstCitationCard)

    expect(citationCard.getByText('未生成增强语义。')).toBeInTheDocument()
    expect(citationCard.queryByText('中性')).not.toBeInTheDocument()
    expect(citationCard.getByRole('button', { name: '提及证据未生成' })).toBeDisabled()
  })
})
