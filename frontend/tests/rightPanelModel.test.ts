import { describe, expect, test } from 'vitest'

import { buildNodeContentState, filterEvidenceRows, rankRelationRows } from '../src/components/rightPanelModel'

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
})
