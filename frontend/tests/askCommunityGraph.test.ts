import { describe, expect, test } from 'vitest'

import { buildAskGraph } from '../src/loaders/ask'

describe('ask community graph builder', () => {
  test('renders community nodes with member nodes and evidence links below the members', () => {
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
          kind: 'community',
          source_id: 'gc:demo',
          community_id: 'gc:demo',
          text: 'Finite element stability community.',
          member_ids: ['cl-1', 'ent-1'],
          member_kinds: ['claim', 'entity'],
          keyword_texts: ['finite element', 'stability'],
          score: 0.82,
        },
      ],
      grounding: [
        {
          source_kind: 'claim',
          source_id: 'cl-1',
          quote: 'Finite element method discretizes the domain.',
          paper_source: 'paper-A',
          paper_id: 'doi:10.1000/example',
          chunk_id: 'c1',
          md_path: 'C:\\papers\\paper-A\\paper.md',
          start_line: 8,
          end_line: 20,
        },
      ],
      graph_context: [],
      dual_evidence_coverage: true,
    } as any)

    const nodes = graph.filter((item) => item.group === 'nodes').map((item) => item.data)
    const edges = graph.filter((item) => item.group === 'edges').map((item) => item.data)

    expect(nodes.some((node) => node.id === 'community:gc:demo' && node.kind === 'community')).toBe(true)
    expect(nodes.some((node) => node.id === 'claim:cl-1' && node.kind === 'claim')).toBe(true)
    expect(nodes.some((node) => node.id === 'entity:ent-1' && node.kind === 'entity')).toBe(true)
    expect(edges.some((edge) => edge.source === 'community:gc:demo' && edge.target === 'claim:cl-1' && edge.kind === 'contains')).toBe(true)
    expect(edges.some((edge) => edge.source === 'community:gc:demo' && edge.target === 'entity:ent-1' && edge.kind === 'contains')).toBe(true)
    expect(edges.some((edge) => edge.source === 'claim:cl-1' && String(edge.target).startsWith('evidence:') && edge.kind === 'evidenced_by')).toBe(true)
  })
})
