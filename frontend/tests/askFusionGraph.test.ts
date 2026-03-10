import { describe, expect, test } from 'vitest'

import { buildAskGraph } from '../src/loaders/ask'

describe('ask fusion graph builder', () => {
  test('maps fusion evidence into textbook, chapter, and entity nodes linked back to paper logic', () => {
    const graph = buildAskGraph({
      answer: 'ok',
      evidence: [
        {
          paper_id: 'doi:10.1000/example',
          paper_source: 'paper-A',
          paper_title: 'Paper A',
          md_path: 'C:\\papers\\paper-A\\paper.md',
          start_line: 8,
          end_line: 20,
          snippet: 'evidence snippet',
        },
      ],
      fusion_evidence: [
        {
          paper_id: 'doi:10.1000/example',
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
          chapter_title: 'Finite Element Foundations',
          chapter_num: 1,
          score: 0.84,
          evidence_quote: 'Finite element method discretizes the domain.',
        },
      ],
      graph_context: [],
      structured_knowledge: {
        logic_steps: [{ paper_source: 'paper-A', step_type: 'Method', summary: 'Uses FEM for discretization.' }],
        claims: [],
      },
      dual_evidence_coverage: true,
    })

    const nodes = graph.filter((item) => item.group === 'nodes').map((item) => item.data)
    const edges = graph.filter((item) => item.group === 'edges').map((item) => item.data)

    expect(nodes.some((node) => node.id === 'textbook:tb:1' && node.kind === 'textbook')).toBe(true)
    expect(nodes.some((node) => node.id === 'chapter:tb:1:ch001' && node.kind === 'chapter')).toBe(true)
    expect(nodes.some((node) => node.id === 'entity:ent-1' && node.kind === 'entity')).toBe(true)
    expect(edges.some((edge) => edge.source === 'textbook:tb:1' && edge.target === 'chapter:tb:1:ch001' && edge.kind === 'contains')).toBe(true)
    expect(edges.some((edge) => edge.source === 'chapter:tb:1:ch001' && edge.target === 'entity:ent-1' && edge.kind === 'contains')).toBe(true)
    expect(edges.some((edge) => edge.source.startsWith('logic:') && edge.target === 'entity:ent-1' && edge.kind === 'maps_to')).toBe(true)
  })
})
