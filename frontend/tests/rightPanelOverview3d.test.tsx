import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, test, vi } from 'vitest'

import type { GlobalState } from '../src/state/types'
import { INITIAL_STATE } from '../src/state/store'

const {
  apiGetMock,
  dispatchMock,
  loadOverviewCommunity3DGraphMock,
  loadOverviewCommunitySubgraphMock,
  loadOverviewGraphMock,
} = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  dispatchMock: vi.fn(),
  loadOverviewCommunity3DGraphMock: vi.fn(),
  loadOverviewCommunitySubgraphMock: vi.fn(),
  loadOverviewGraphMock: vi.fn(),
}))

let mockedState: GlobalState = INITIAL_STATE

vi.mock('../src/api', () => ({
  apiGet: apiGetMock,
}))

vi.mock('../src/loaders/overview', async () => {
  const actual = await vi.importActual<typeof import('../src/loaders/overview')>('../src/loaders/overview')
  return {
    ...actual,
    loadOverviewCommunity3DGraph: loadOverviewCommunity3DGraphMock,
    loadOverviewCommunitySubgraph: loadOverviewCommunitySubgraphMock,
    loadOverviewGraph: loadOverviewGraphMock,
  }
})

vi.mock('../src/state/store', async () => {
  const actual = await vi.importActual<typeof import('../src/state/store')>('../src/state/store')
  return {
    ...actual,
    useGlobalState: () => ({
      state: mockedState,
      dispatch: dispatchMock,
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
    dispatchMock.mockReset()
    loadOverviewCommunity3DGraphMock.mockReset()
    loadOverviewCommunitySubgraphMock.mockReset()
    loadOverviewGraphMock.mockReset()
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
    expect(loadOverviewCommunity3DGraphMock).toHaveBeenCalledWith()
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
    expect(loadOverviewCommunity3DGraphMock).toHaveBeenCalledWith()
    await waitFor(() => expect(screen.getAllByText('P-001').length).toBeGreaterThan(0))
  })

  test('expands the selected overview community into its own subgraph from the sidebar action', async () => {
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
    loadOverviewCommunitySubgraphMock.mockResolvedValue([
      {
        group: 'nodes',
        data: {
          id: 'community:gc:alpha',
          label: 'Alpha stability',
          kind: 'community',
          description: 'Focus on alpha pathways',
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
          paperSource: 'P-001',
          paperTitle: 'Alpha Study',
          stepType: 'Method',
        },
      },
      {
        group: 'nodes',
        data: {
          id: 'logic:logic-1',
          label: 'Logic chain that explains the alpha workflow.',
          kind: 'logic',
          description: 'Alpha Study | Logic chain that explains the alpha workflow.',
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
      {
        group: 'edges',
        data: {
          id: 'contains:community:gc:alpha->logic:logic-1',
          source: 'community:gc:alpha',
          target: 'logic:logic-1',
          kind: 'contains',
          weight: 0.81,
        },
      },
    ])

    render(<RightPanel collapsed={false} onToggle={() => {}} />)

    const button = await screen.findByRole('button', { name: 'Expand Community' })
    fireEvent.click(button)

    await waitFor(() => expect(loadOverviewCommunitySubgraphMock).toHaveBeenCalledWith('gc:alpha'))
    await waitFor(() =>
      expect(dispatchMock).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'SET_GRAPH',
          layout: 'cose',
        }),
      ),
    )
    expect(dispatchMock).toHaveBeenCalledWith({
      type: 'SET_SELECTED',
      node: expect.objectContaining({
        id: 'community:gc:alpha',
        kind: 'community',
        label: 'Alpha stability',
      }),
    })
  })

  test('offers a return action when the overview is already focused on a single community subgraph', async () => {
    mockedState = {
      ...INITIAL_STATE,
      activeModule: 'overview',
      graphElements: [
        {
          group: 'nodes',
          data: {
            id: 'community:gc:alpha',
            label: 'Alpha stability',
            kind: 'community',
            description: 'Focus on alpha pathways',
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
      ],
      selectedNode: {
        id: 'community:gc:alpha',
        kind: 'community',
        label: 'Alpha stability',
      },
    }
    loadOverviewGraphMock.mockResolvedValue([
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
    ])

    render(<RightPanel collapsed={false} onToggle={() => {}} />)

    const buttons = await screen.findAllByRole('button', { name: 'Return to Overview' })
    fireEvent.click(buttons[0])

    await waitFor(() => expect(loadOverviewGraphMock).toHaveBeenCalledTimes(1))
    await waitFor(() =>
      expect(dispatchMock).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'SET_GRAPH',
          layout: 'cose',
        }),
      ),
    )
  })
})
