import { describe, expect, test } from 'vitest'

import {
  buildGenericNodeContext,
  buildNodeContentState,
  filterEvidenceRows,
  rankRelationRows,
} from '../src/components/rightPanelModel'

describe('rightPanelModel', () => {
  test('buildNodeContentState prefers description and provides collapsed preview', () => {
    const longText = `${'A'.repeat(120)} ${'B'.repeat(120)}`
    const state = buildNodeContentState({
      label: 'fallback label',
      description: longText,
      maxChars: 80,
    })

    expect(state.full).toBe(longText)
    expect(state.preview.length).toBeLessThan(state.full.length)
    expect(state.truncated).toBe(true)
  })

  test('rankRelationRows sorts by count and keeps top entries', () => {
    const rows = rankRelationRows(
      [
        { kind: 'supports', label: 'supports', count: 3 },
        { kind: 'cites', label: 'cites', count: 10 },
        { kind: 'contains', label: 'contains', count: 5 },
      ],
      2,
    )

    expect(rows).toHaveLength(2)
    expect(rows.map((row) => row.kind)).toEqual(['cites', 'contains'])
  })

  test('filterEvidenceRows applies keyword filtering and score ranking', () => {
    const rows = filterEvidenceRows(
      [
        {
          paper_id: 'P-1',
          paper_source: 'Alpha',
          snippet: 'granular flow experiment baseline',
          score: 0.33,
        },
        {
          paper_id: 'P-2',
          paper_source: 'Beta',
          snippet: 'Granular flow improves with model tuning',
          score: 0.91,
        },
        {
          paper_id: 'P-3',
          paper_source: 'Gamma',
          snippet: 'unrelated topic',
          score: 0.8,
        },
      ],
      'granular',
      1,
    )

    expect(rows).toHaveLength(1)
    expect(rows[0]?.paper_id).toBe('P-2')
  })

  test('filterEvidenceRows supports paper title keyword search', () => {
    const rows = filterEvidenceRows(
      [
        { paper_id: 'P-1', paper_title: 'Granular Mixing Baseline', score: 0.5 },
        { paper_id: 'P-2', paper_title: 'Ribbon Blender Dynamics', score: 0.9 },
      ],
      'ribbon',
      5,
    )

    expect(rows).toHaveLength(1)
    expect(rows[0]?.paper_id).toBe('P-2')
  })

  test('buildGenericNodeContext separates child and parent neighbors', () => {
    const context = buildGenericNodeContext({
      selectedNode: { id: 'paper:A', kind: 'paper', label: 'Paper A' },
      nodes: [
        { id: 'paper:A', label: 'P-A', description: 'Full Paper A Title', kind: 'paper', year: 2021 },
        { id: 'paper:B', label: 'P-B', description: 'Full Paper B Title', kind: 'paper', year: 2022 },
        { id: 'paper:C', label: 'Paper C', kind: 'paper', year: 2020 },
        { id: 'paper:D', label: 'P-D', description: 'Full Paper D Title', kind: 'paper', year: 2023 },
      ],
      edges: [
        { id: 'ab', source: 'paper:A', target: 'paper:B', kind: 'cites' },
        { id: 'ca', source: 'paper:C', target: 'paper:A', kind: 'supports' },
        { id: 'ad', source: 'paper:A', target: 'paper:D', kind: 'relates_to' },
        { id: 'da', source: 'paper:D', target: 'paper:A', kind: 'challenges' },
      ],
    })

    expect(context).not.toBeNull()
    expect(context?.childNeighbors.map((row) => row.id)).toEqual(['paper:D', 'paper:B'])
    expect(context?.parentNeighbors.map((row) => row.id)).toEqual(['paper:D', 'paper:C'])
    expect(context?.center?.description).toBe('Full Paper A Title')
    expect(context?.childNeighbors[0]?.label).toBe('Full Paper D Title')
    expect(context?.childNeighbors[1]?.label).toBe('Full Paper B Title')
    expect(context?.neighborCount).toBe(3)
    expect(context?.outCount).toBe(2)
    expect(context?.inCount).toBe(2)
  })
})
