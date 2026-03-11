import { describe, expect, test } from 'vitest'

import { buildAskGraph, resolveAskGraph } from '../src/loaders/ask'

describe('ask loader graph builder', () => {
  test('buildAskGraph keeps evidence nodes even when paper_source is missing', () => {
    const graph = buildAskGraph({
      answer: 'ok',
      evidence: [
        {
          md_path: 'C:\\papers\\02_1050\\paper.md',
          start_line: 10,
          end_line: 20,
          score: 0.9,
          snippet: 'evidence snippet',
        },
      ],
      graph_context: [],
      structured_knowledge: null,
    })

    const nodes = graph.filter((item) => item.group === 'nodes')
    expect(nodes.length).toBeGreaterThan(0)
    expect(nodes.some((item) => String(item.data.id).startsWith('paper_source:') || String(item.data.id).startsWith('paper_file:'))).toBe(
      true,
    )
  })

  test('resolveAskGraph falls back to overview graph when ask graph is empty', () => {
    const fallbackGraph = [
      {
        group: 'nodes' as const,
        data: { id: 'paper:seed', label: 'Seed Paper', kind: 'paper' },
      },
    ]

    const graph = resolveAskGraph(
      {
        answer: '',
        evidence: [],
        graph_context: [],
        structured_knowledge: null,
      },
      fallbackGraph,
    )

    expect(graph).toBe(fallbackGraph)
    expect(graph).toHaveLength(1)
  })

  test('buildAskGraph adds evidence nodes linked to paper nodes', () => {
    const graph = buildAskGraph({
      answer: 'ok',
      evidence: [
        {
          paper_source: 'paper-A',
          md_path: 'C:\\papers\\paper-A\\paper.md',
          start_line: 12,
          end_line: 18,
          snippet: 'snippet A',
        },
      ],
      graph_context: [],
      structured_knowledge: null,
    })

    const nodes = graph.filter((item) => item.group === 'nodes')
    const edges = graph.filter((item) => item.group === 'edges')
    expect(nodes.length).toBeGreaterThanOrEqual(2)
    expect(nodes.some((item) => String(item.data.id).startsWith('evidence:'))).toBe(true)
    expect(edges.some((item) => item.data.kind === 'evidenced_by')).toBe(true)
  })

  test('resolveAskGraph prefers a community-first ask graph over the fallback graph', () => {
    const fallbackGraph = [
      {
        group: 'nodes' as const,
        data: { id: 'paper:seed', label: 'Seed Paper', kind: 'paper' },
      },
    ]

    const graph = resolveAskGraph(
      {
        answer: 'ok',
        evidence: [],
        graph_context: [],
        fusion_evidence: [],
        structured_knowledge: null,
        grounding: [],
        structured_evidence: [
          {
            kind: 'community',
            source_id: 'gc:demo',
            community_id: 'gc:demo',
            text: 'Finite element stability community.',
            member_ids: ['cl-1', 'ke-1'],
            member_kinds: ['claim', 'entity'],
            keyword_texts: ['finite element', 'stability'],
            score: 0.82,
          },
        ],
      } as any,
      fallbackGraph,
    )

    expect(graph).not.toBe(fallbackGraph)
    expect(graph.some((item) => item.group === 'nodes' && item.data.kind === 'community')).toBe(true)
  })

  test('buildAskGraph keeps full description text for claim/logic/citation/entity node details', () => {
    const longClaim =
      'Mixing performance strongly correlates with impeller speed and fill level, and the effect remains stable across repeated trials without significant drift.'
    const longLogic =
      'We first establish the baseline flow regime, then compare perturbation cases under controlled boundary conditions to isolate the dominant mixing factors.'
    const longCitation =
      'A comprehensive review on granular mixing mechanisms in rotating drum and ribbon systems'
    const longEvidence =
      'This evidence snippet includes detailed context about measurement setup, sampling interval, and confidence calibration to support the claim.'

    const graph = buildAskGraph({
      answer: 'ok',
      evidence: [
        {
          paper_source: 'paper-A',
          md_path: 'C:\\papers\\paper-A\\paper.md',
          start_line: 12,
          end_line: 18,
          snippet: longEvidence,
        },
      ],
      graph_context: [
        {
          paper_source: 'paper-A',
          cited_title: longCitation,
        },
      ],
      structured_knowledge: {
        logic_steps: [{ paper_source: 'paper-A', step_type: 'Method', summary: longLogic }],
        claims: [{ paper_source: 'paper-A', step_type: 'Result', text: longClaim, confidence: 0.9 }],
      },
    })

    const nodes = graph.filter((item) => item.group === 'nodes').map((item) => item.data)
    const claimNode = nodes.find((node) => node.kind === 'claim')
    const logicNode = nodes.find((node) => node.kind === 'logic')
    const citationNode = nodes.find((node) => node.kind === 'citation')
    const evidenceNode = nodes.find((node) => node.kind === 'entity' && String(node.id).startsWith('evidence:'))

    expect(claimNode?.description).toContain('Mixing performance strongly correlates')
    expect(logicNode?.description).toContain('baseline flow regime')
    expect(citationNode?.description).toContain('granular mixing mechanisms')
    expect(evidenceNode?.description).toContain('measurement setup')
  })

  test('buildAskGraph prefers paper_title for paper node labels and descriptions', () => {
    const graph = buildAskGraph({
      answer: 'ok',
      evidence: [
        {
          paper_id: 'doi:10.1000/example',
          paper_source: 'paper-A',
          paper_title: 'A Unified Framework for Granular Mixing',
          md_path: 'C:\\papers\\paper-A\\paper.md',
          start_line: 8,
          end_line: 20,
          snippet: 'evidence snippet',
        },
      ],
      graph_context: [
        {
          paper_source: 'paper-A',
          cited_title: 'Related Prior Work',
        },
      ],
      structured_knowledge: {
        logic_steps: [{ paper_source: 'paper-A', step_type: 'Method', summary: 'Method summary' }],
        claims: [{ paper_source: 'paper-A', step_type: 'Result', text: 'Result claim', confidence: 0.9 }],
      },
    })

    const nodes = graph.filter((item) => item.group === 'nodes').map((item) => item.data)
    const paperNode = nodes.find((node) => node.id === 'paper:doi:10.1000/example')

    expect(paperNode?.kind).toBe('paper')
    expect(paperNode?.label).toBe('A Unified Framework for Granular Mixing')
    expect(paperNode?.description).toBe('A Unified Framework for Granular Mixing')
  })
})
