import { describe, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { GlobalState } from '../src/state/types'
import { INITIAL_STATE } from '../src/state/store'

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

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  }
})

import RightPanel from '../src/components/RightPanel'

describe('RightPanel ask summary fusion coverage', () => {
  test('renders textbook anchor summary and top anchored chapters for ask results', () => {
    mockedState = {
      ...INITIAL_STATE,
      activeModule: 'ask',
      graphElements: [
        { group: 'nodes', data: { id: 'paper:doi:1', label: 'Paper A', kind: 'paper', paperId: 'doi:1' } },
        { group: 'nodes', data: { id: 'logic:paper-A:Method:Uses FEM', label: 'Uses FEM', kind: 'logic' } },
        { group: 'nodes', data: { id: 'textbook:tb:1', label: 'Continuum Mechanics', kind: 'textbook', textbookId: 'tb:1', clusterKey: 'textbook:tb:1' } },
        { group: 'nodes', data: { id: 'chapter:tb:1:ch001', label: 'Ch.1 Finite Element Foundations', kind: 'chapter', textbookId: 'tb:1', chapterId: 'tb:1:ch001', clusterKey: 'textbook:tb:1' } },
        { group: 'nodes', data: { id: 'entity:ent-1', label: 'Finite Element Method', kind: 'entity', textbookId: 'tb:1', chapterId: 'tb:1:ch001', clusterKey: 'chapter:tb:1:ch001' } },
        { group: 'edges', data: { id: 'paper:doi:1->logic:paper-A:Method:Uses FEM', source: 'paper:doi:1', target: 'logic:paper-A:Method:Uses FEM', kind: 'contains' } },
        { group: 'edges', data: { id: 'textbook:tb:1->chapter:tb:1:ch001', source: 'textbook:tb:1', target: 'chapter:tb:1:ch001', kind: 'contains' } },
        { group: 'edges', data: { id: 'chapter:tb:1:ch001->entity:ent-1', source: 'chapter:tb:1:ch001', target: 'entity:ent-1', kind: 'contains' } },
        { group: 'edges', data: { id: 'logic:paper-A:Method:Uses FEM->entity:ent-1', source: 'logic:paper-A:Method:Uses FEM', target: 'entity:ent-1', kind: 'maps_to' } },
      ],
      ask: {
        sessions: [
          {
            id: 'session-1',
            title: 'FEM grounding',
            createdAt: 1,
            updatedAt: 1,
            history: [
              {
                id: 'ask-1',
                question: 'How is FEM grounded in textbooks?',
                k: 8,
                createdAt: 1,
                status: 'done',
                answer: 'FEM is grounded in the finite element chapter.',
                evidence: [
                  {
                    paper_id: 'doi:1',
                    paper_source: 'paper-A',
                    paper_title: 'Paper A',
                    start_line: 10,
                    end_line: 20,
                    score: 0.91,
                    snippet: 'Uses FEM for discretization.',
                  },
                ],
                fusionEvidence: [
                  {
                    paper_id: 'doi:1',
                    paper_source: 'paper-A',
                    logic_step_id: 'ls-1',
                    step_type: 'Method',
                    entity_id: 'ent-1',
                    entity_name: 'Finite Element Method',
                    entity_type: 'method',
                    description: 'Numerical discretization method',
                    textbook_id: 'tb:1',
                    textbook_title: 'Continuum Mechanics',
                    chapter_id: 'tb:1:ch001',
                    chapter_num: 1,
                    chapter_title: 'Finite Element Foundations',
                    score: 0.84,
                    evidence_quote: 'Finite element method discretizes the domain.',
                  },
                ],
                dualEvidenceCoverage: true,
                graphContext: [],
                structuredKnowledge: {
                  logic_steps: [{ paper_source: 'paper-A', step_type: 'Method', summary: 'Uses FEM.' }],
                  claims: [{ claim_id: 'cl-1', paper_source: 'paper-A', step_type: 'Result', text: 'FEM improves stability.' }],
                },
                structuredEvidence: [
                  {
                    kind: 'community',
                    source_id: 'gc:finite-element',
                    community_id: 'gc:finite-element',
                    text: 'Finite element stability community.',
                    source_kind: 'claim',
                    source_ref_id: 'cl-1',
                    member_ids: ['cl-1', 'ent-1'],
                    member_kinds: ['claim', 'entity'],
                    keyword_texts: ['finite element', 'stability'],
                  },
                ],
                grounding: [
                  {
                    source_kind: 'claim',
                    source_id: 'cl-1',
                    quote: 'Finite element method discretizes the domain.',
                    chunk_id: 'c1',
                    chapter_id: 'tb:1:ch001',
                    start_line: 11,
                    end_line: 13,
                  },
                ],
                intent: 'foundational',
                retrievalPlan: 'textbook_first_then_paper',
                queryPlan: {
                  main_query: 'finite element method assumptions',
                  textbook_query: 'finite element method definition assumptions discretization',
                  community_query: 'finite element method assumptions community',
                },
                retrievalMode: 'hybrid',
                notice: '',
              },
            ],
            currentId: 'ask-1',
            draftQuestion: '',
            draftK: 8,
          },
        ],
        currentSessionId: 'session-1',
        history: [
          {
            id: 'ask-1',
            question: 'How is FEM grounded in textbooks?',
            k: 8,
            createdAt: 1,
            status: 'done',
            answer: 'FEM is grounded in the finite element chapter.',
            evidence: [
              {
                paper_id: 'doi:1',
                paper_source: 'paper-A',
                paper_title: 'Paper A',
                start_line: 10,
                end_line: 20,
                score: 0.91,
                snippet: 'Uses FEM for discretization.',
              },
            ],
            fusionEvidence: [
              {
                paper_id: 'doi:1',
                paper_source: 'paper-A',
                logic_step_id: 'ls-1',
                step_type: 'Method',
                entity_id: 'ent-1',
                entity_name: 'Finite Element Method',
                entity_type: 'method',
                description: 'Numerical discretization method',
                textbook_id: 'tb:1',
                textbook_title: 'Continuum Mechanics',
                chapter_id: 'tb:1:ch001',
                chapter_num: 1,
                chapter_title: 'Finite Element Foundations',
                score: 0.84,
                evidence_quote: 'Finite element method discretizes the domain.',
              },
            ],
            dualEvidenceCoverage: true,
            graphContext: [],
            structuredKnowledge: {
              logic_steps: [{ paper_source: 'paper-A', step_type: 'Method', summary: 'Uses FEM.' }],
              claims: [{ claim_id: 'cl-1', paper_source: 'paper-A', step_type: 'Result', text: 'FEM improves stability.' }],
            },
            structuredEvidence: [
              {
                kind: 'community',
                source_id: 'gc:finite-element',
                community_id: 'gc:finite-element',
                text: 'Finite element stability community.',
                source_kind: 'claim',
                source_ref_id: 'cl-1',
                member_ids: ['cl-1', 'ent-1'],
                member_kinds: ['claim', 'entity'],
                keyword_texts: ['finite element', 'stability'],
              },
            ],
            grounding: [
              {
                source_kind: 'claim',
                source_id: 'cl-1',
                quote: 'Finite element method discretizes the domain.',
                chunk_id: 'c1',
                chapter_id: 'tb:1:ch001',
                start_line: 11,
                end_line: 13,
              },
            ],
            intent: 'foundational',
            retrievalPlan: 'textbook_first_then_paper',
            queryPlan: {
              main_query: 'finite element method assumptions',
              textbook_query: 'finite element method definition assumptions discretization',
              community_query: 'finite element method assumptions community',
            },
            retrievalMode: 'hybrid',
            notice: '',
          },
        ],
        currentId: 'ask-1',
        draftQuestion: '',
        draftK: 8,
      },
    }

    const html = renderToStaticMarkup(<RightPanel collapsed={false} onToggle={() => {}} />)

    expect(html).toContain('Textbook Anchors')
    expect(html).toContain('Dual Evidence')
    expect(html).toContain('Top Anchored Chapters')
    expect(html).toContain('Ch.1 Finite Element Foundations')
    expect(html).toContain('Covered')
    expect(html).toContain('Foundational')
    expect(html).toContain('textbook_first_then_paper')
    expect(html).toContain('Structured Evidence')
    expect(html).toContain('Community Keywords')
    expect(html).toContain('Representative Members')
    expect(html).toContain('finite element, stability')
    expect(html).toContain('FEM improves stability.')
    expect(html).toContain('Finite Element Method')
    expect(html).toContain('Finite element method discretizes the domain.')
    expect(html).toContain('c1')
    expect(html).toContain('Lines 11-13')
  })
})
