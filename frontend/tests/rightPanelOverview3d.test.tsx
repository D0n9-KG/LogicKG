import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'

import type { GlobalState } from '../src/state/types'
import { INITIAL_STATE } from '../src/state/store'

const { apiGetMock, loadOverviewCommunity3DGraphMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  loadOverviewCommunity3DGraphMock: vi.fn(),
}))

let mockedState: GlobalState = INITIAL_STATE

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
}))

vi.mock('../src/loaders/overview', () => ({
  loadOverviewCommunity3DGraph: loadOverviewCommunity3DGraphMock,
}))

vi.mock('../src/state/store', async () => {
  const actual = await vi.importActual<typeof import('../src/state/store')>('../src/state/store')
  return {
    ...actual,
    useGlobalState: () => ({
      state: mockedState,
      dispatch: vi.fn(),
      switchModule: vi.fn(),
    }),
  }
})

vi.mock('../src/i18n', async () => {
  const actual = await vi.importActual<typeof import('../src/i18n')>('../src/i18n')
  return {
    ...actual,
    useI18n: () => ({
      locale: 'en-US',
      setLocale: vi.fn(),
      t: (_zh: string, en: string) => en,
    }),
  }
})

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  }
})

import RightPanel from '../src/components/RightPanel'

describe('RightPanel overview 3D node details', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    loadOverviewCommunity3DGraphMock.mockReset()
    apiGetMock.mockResolvedValue({
      title: 'Alpha Study',
      paper_source: 'P-001',
      logic_steps: [{ step_type: 'Method', summary: 'Method summary' }],
      claims: [{ step_type: 'Method', text: 'Claim summary' }],
    })
    mockedState = {
      ...INITIAL_STATE,
      activeModule: 'overview',
      graphElements: [
        {
          group: 'nodes',
          data: {
            id: 'paper:paper-1',
            label: 'P-001',
            description: 'Alpha Study',
            kind: 'paper',
            paperId: 'paper-1',
          },
        },
      ],
      selectedNode: {
        id: 'claim:claim-1',
        kind: 'claim',
        label: 'Alpha claim with the strongest signal.',
      },
    }
  })

  test('loads 3D overview graph context when the selected node is absent from the main overview graph', async () => {
    loadOverviewCommunity3DGraphMock.mockResolvedValue([
      {
        group: 'nodes',
        data: {
          id: 'community:gc:alpha',
          label: 'Alpha stability',
          kind: 'community',
          description: 'Top keywords: alpha, fem',
          communityId: 'gc:alpha',
          clusterKey: 'community:gc:alpha',
        },
      },
      {
        group: 'nodes',
        data: {
          id: 'claim:claim-1',
          label: 'Alpha claim with the strongest signal.',
          kind: 'claim',
          description: 'Alpha claim with the strongest signal.',
          communityId: 'gc:alpha',
          clusterKey: 'community:gc:alpha',
          paperId: 'paper-1',
          paperSource: 'P-001',
          paperTitle: 'Alpha Study',
          stepType: 'Method',
        },
      },
      {
        group: 'edges',
        data: {
          id: 'contains:community:gc:alpha->claim:claim-1',
          source: 'community:gc:alpha',
          target: 'claim:claim-1',
          kind: 'contains',
          weight: 0.92,
        },
      },
    ])

    render(<RightPanel collapsed={false} onToggle={() => {}} />)

    await waitFor(() => expect(loadOverviewCommunity3DGraphMock).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getAllByText('P-001').length).toBeGreaterThan(0))
    expect(screen.getAllByText('Alpha Study').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Method').length).toBeGreaterThan(0)
  })

  test('falls back to paper preview metadata when a 3D claim node is missing paper source', async () => {
    loadOverviewCommunity3DGraphMock.mockResolvedValue([
      {
        group: 'nodes',
        data: {
          id: 'community:gc:alpha',
          label: 'Alpha stability',
          kind: 'community',
          description: 'Top keywords: alpha, fem',
          communityId: 'gc:alpha',
          clusterKey: 'community:gc:alpha',
        },
      },
      {
        group: 'nodes',
        data: {
          id: 'claim:claim-1',
          label: 'Alpha claim with the strongest signal.',
          kind: 'claim',
          description: 'Alpha Study | Method | Alpha claim with the strongest signal.',
          communityId: 'gc:alpha',
          clusterKey: 'community:gc:alpha',
          paperId: 'paper-1',
          paperTitle: 'Alpha Study',
          stepType: 'Method',
        },
      },
      {
        group: 'edges',
        data: {
          id: 'contains:community:gc:alpha->claim:claim-1',
          source: 'community:gc:alpha',
          target: 'claim:claim-1',
          kind: 'contains',
          weight: 0.92,
        },
      },
    ])

    render(<RightPanel collapsed={false} onToggle={() => {}} />)

    await waitFor(() => expect(loadOverviewCommunity3DGraphMock).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getAllByText('P-001').length).toBeGreaterThan(0))
  })
})
