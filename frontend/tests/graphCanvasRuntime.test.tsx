import { describe, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { INITIAL_STATE } from '../src/state/store'
import type { GlobalState, GraphElement } from '../src/state/types'

let mockedState: GlobalState = INITIAL_STATE

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

import GraphCanvas from '../src/components/GraphCanvas'

function buildPaperGraph(): GraphElement[] {
  return [
    { group: 'nodes', data: { id: 'paper:1', label: 'Paper 1', kind: 'paper', paperId: 'paper:1' } },
    { group: 'nodes', data: { id: 'paper:2', label: 'Paper 2', kind: 'paper', paperId: 'paper:2' } },
    { group: 'edges', data: { id: 'cites:1->2', source: 'paper:1', target: 'paper:2', kind: 'cites', weight: 0.8 } },
  ]
}

describe('GraphCanvas runtime view state', () => {
  test('renders non-overview modules with the raw mesh view on the first render', () => {
    const elements = buildPaperGraph()
    mockedState = {
      ...INITIAL_STATE,
      activeModule: 'papers',
      graphElements: elements,
      graphLayout: 'cose',
      graphUpdateReason: 'replace',
    }

    const markup = renderToStaticMarkup(
      <GraphCanvas
        elements={elements}
        layout="cose"
        layoutTrigger={1}
        overviewMode="3d"
        onOverviewModeChange={() => {}}
        transitioning={false}
        onSelectNode={() => {}}
      />,
    )

    expect(markup).toContain('kgGraphControlChip is-active')
    expect(markup).toContain('Base force-directed mesh layout">Raw Mesh</button>')
    expect(markup).not.toContain('Timeline Axis')
  })
})
