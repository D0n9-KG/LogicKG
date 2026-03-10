import { describe, expect, test } from 'vitest'

import { buildAskGraph } from '../src/loaders/ask'

describe('ask proposition graph builder', () => {
  test('renders proposition nodes and connects them to claim, logic, and textbook entity anchors', () => {
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
      structured_knowledge: {
        logic_steps: [{ paper_source: 'paper-A', step_type: 'Method', summary: 'Uses FEM for discretization.' }],
        claims: [{ claim_id: 'cl-1', paper_source: 'paper-A', step_type: 'Method', text: 'FEM improves stability.' }],
      },
      structured_evidence: [
        {
          kind: 'proposition',
          source_id: 'pr-1',
          proposition_id: 'pr-1',
          text: 'Finite element discretization stabilizes PDE solving.',
          source_kind: 'claim',
          source_ref_id: 'cl-1',
          paper_source: 'paper-A',
          entity_id: 'ent-1',
          textbook_id: 'tb:1',
          chapter_id: 'tb:1:ch001',
        },
      ],
      grounding: [
        {
          source_kind: 'proposition',
          source_id: 'pr-1',
          quote: 'Finite element method discretizes the domain.',
          textbook_id: 'tb:1',
          chapter_id: 'tb:1:ch001',
        },
      ],
      graph_context: [],
      dual_evidence_coverage: true,
    } as any)

    const nodes = graph.filter((item) => item.group === 'nodes').map((item) => item.data)
    const edges = graph.filter((item) => item.group === 'edges').map((item) => item.data)

    expect(nodes.some((node) => node.id === 'proposition:pr-1' && node.kind === 'proposition')).toBe(true)
    expect(edges.some((edge) => edge.source === 'claim:cl-1' && edge.target === 'proposition:pr-1' && edge.kind === 'supports')).toBe(true)
    expect(edges.some((edge) => edge.source.startsWith('logic:') && edge.target === 'proposition:pr-1' && edge.kind === 'supports')).toBe(true)
    expect(edges.some((edge) => edge.source === 'proposition:pr-1' && edge.target === 'entity:ent-1' && edge.kind === 'maps_to')).toBe(true)
  })
})
