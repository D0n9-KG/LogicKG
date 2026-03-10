import { describe, expect, test } from 'vitest'

import { buildFusionEvidenceStats, filterFusionEvidenceRows } from '../src/components/rightPanelModel'

describe('rightPanelModel fusion evidence helpers', () => {
  const rows = [
    {
      paper_source: 'paper-A',
      textbook_id: 'tb:1',
      textbook_title: 'Continuum Mechanics',
      chapter_id: 'tb:1:ch001',
      chapter_num: 1,
      chapter_title: 'Finite Element Foundations',
      entity_id: 'ent-1',
      entity_name: 'Finite Element Method',
      score: 0.84,
      step_type: 'Method',
      evidence_quote: 'Finite element method discretizes the domain.',
    },
    {
      paper_source: 'paper-A',
      textbook_id: 'tb:1',
      textbook_title: 'Continuum Mechanics',
      chapter_id: 'tb:1:ch001',
      chapter_num: 1,
      chapter_title: 'Finite Element Foundations',
      entity_id: 'ent-2',
      entity_name: 'Galerkin Form',
      score: 0.78,
      step_type: 'Method',
      evidence_quote: 'Galerkin weighted residual form.',
    },
    {
      paper_source: 'paper-B',
      textbook_id: 'tb:2',
      textbook_title: 'Multiphase Flow',
      chapter_id: 'tb:2:ch003',
      chapter_num: 3,
      chapter_title: 'Bubble Dynamics',
      entity_id: 'ent-9',
      entity_name: 'Bubble Collapse',
      score: 0.67,
      step_type: 'Mechanism',
      evidence_quote: 'Bubble collapse drives local pressure rise.',
    },
  ]

  test('builds textbook/chapter/entity coverage stats for ask fusion evidence', () => {
    const stats = buildFusionEvidenceStats(rows)

    expect(stats.total).toBe(3)
    expect(stats.textbookCount).toBe(2)
    expect(stats.chapterCount).toBe(2)
    expect(stats.entityCount).toBe(3)
    expect(stats.paperSourceCount).toBe(2)
    expect(stats.avgScore).toBeCloseTo((0.84 + 0.78 + 0.67) / 3, 5)
    expect(stats.topChapters[0]).toMatchObject({
      chapterId: 'tb:1:ch001',
      label: 'Ch.1 Finite Element Foundations',
      count: 2,
    })
  })

  test('filters fusion evidence by textbook, chapter, entity, and quote text', () => {
    expect(filterFusionEvidenceRows(rows, 'bubble', 10)).toHaveLength(1)
    expect(filterFusionEvidenceRows(rows, 'continuum mechanics', 10)).toHaveLength(2)
    expect(filterFusionEvidenceRows(rows, 'Galerkin', 10)[0]?.entity_name).toBe('Galerkin Form')
  })
})
