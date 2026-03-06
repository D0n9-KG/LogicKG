import { describe, expect, test } from 'vitest'

import type { AskItem } from '../src/state/types'
import {
  assistantTurnText,
  buildChatMessages,
  buildEvidenceStats,
  buildScopePaperOptions,
  getScopePaperRenderState,
  nextStreamRevealLength,
  shouldAutoRetryWithAllScope,
  toConversationTurns,
  toggleScopePaperIds,
} from '../src/panels/askPanelModel'

describe('askPanelModel', () => {
  test('buildScopePaperOptions only uses api catalog papers and deduplicates ids', () => {
    const apiRows = [
      { id: 'paper-2', label: 'API Paper 2', year: 2024 },
      { id: 'paper-3', label: 'API Paper 3', year: 2022 },
      { id: 'paper-2', label: 'API Paper 2 Latest', year: 2025 },
    ]

    const options = buildScopePaperOptions(apiRows)

    expect(options.map((item) => item.id)).toEqual(['paper-2', 'paper-3'])
    expect(options.find((item) => item.id === 'paper-2')?.label).toBe('API Paper 2 Latest')
    expect(options.find((item) => item.id === 'paper-2')?.source).toBe('api')
  })

  test('toggleScopePaperIds adds and removes selected paper ids', () => {
    expect(toggleScopePaperIds(['paper-1'], 'paper-2')).toEqual(['paper-1', 'paper-2'])
    expect(toggleScopePaperIds(['paper-1', 'paper-2'], 'paper-1')).toEqual(['paper-2'])
    expect(toggleScopePaperIds(['paper-2', 'paper-2'], 'paper-2')).toEqual([])
  })

  test('toConversationTurns sorts turns by time and marks active turn', () => {
    const history: AskItem[] = [
      { id: 'new', question: 'Q2', k: 8, createdAt: 200, status: 'done', answer: 'A2' },
      { id: 'old', question: 'Q1', k: 8, createdAt: 100, status: 'done', answer: 'A1' },
    ]

    const turns = toConversationTurns(history, 'new')

    expect(turns.map((item) => item.id)).toEqual(['old', 'new'])
    expect(turns.find((item) => item.id === 'new')?.active).toBe(true)
    expect(turns.find((item) => item.id === 'old')?.active).toBe(false)
  })

  test('buildChatMessages expands turns into ordered user and assistant chat bubbles', () => {
    const history: AskItem[] = [
      { id: 't2', question: 'Q2', k: 8, createdAt: 200, status: 'running' },
      { id: 't1', question: 'Q1', k: 8, createdAt: 100, status: 'done', answer: 'A1' },
    ]
    const turns = toConversationTurns(history, 't2')
    const messages = buildChatMessages(turns)

    expect(messages.map((item) => `${item.turnId}:${item.role}`)).toEqual([
      't1:user',
      't1:assistant',
      't2:user',
      't2:assistant',
    ])
    expect(messages.find((item) => item.id === 't1:assistant')?.text).toBe('A1')
    expect(messages.find((item) => item.id === 't2:assistant')?.status).toBe('running')
    expect(messages.find((item) => item.id === 't2:assistant')?.active).toBe(true)
    expect(messages.find((item) => item.id === 't2:assistant')?.k).toBe(8)
  })

  test('shouldAutoRetryWithAllScope only retries when scope is narrowed and answer is empty', () => {
    expect(
      shouldAutoRetryWithAllScope('papers', {
        answer: '',
        insufficient_scope_evidence: true,
      }),
    ).toBe(true)
    expect(
      shouldAutoRetryWithAllScope('collection', {
        answer: 'has answer',
        insufficient_scope_evidence: true,
      }),
    ).toBe(false)
    expect(
      shouldAutoRetryWithAllScope('all', {
        answer: '',
        insufficient_scope_evidence: true,
      }),
    ).toBe(false)
  })

  test('getScopePaperRenderState limits rendered options and reports remaining count', () => {
    const options = Array.from({ length: 8 }).map((_, index) => ({
      id: `paper-${index + 1}`,
      label: `Paper ${index + 1}`,
      source: 'api' as const,
      year: 2020 + index,
    }))
    const state = getScopePaperRenderState(options, 5)
    expect(state.visible.map((item) => item.id)).toEqual(['paper-1', 'paper-2', 'paper-3', 'paper-4', 'paper-5'])
    expect(state.hasMore).toBe(true)
    expect(state.remaining).toBe(3)
  })

  test('assistantTurnText prefers answer, then notice, and handles running/error states', () => {
    expect(assistantTurnText({ status: 'running' })).toBeTruthy()
    expect(assistantTurnText({ status: 'error', error: 'boom' })).toBe('boom')
    expect(assistantTurnText({ status: 'done', answer: 'A', notice: 'N' })).toBe('A')
    expect(assistantTurnText({ status: 'done', answer: ' ', notice: 'N' })).toBe('N')
  })

  test('nextStreamRevealLength advances progressively and never exceeds source length', () => {
    const text = 'Streaming answer should reveal smoothly for the latest assistant turn.'
    const first = nextStreamRevealLength(text, 0)
    const second = nextStreamRevealLength(text, first)
    const done = nextStreamRevealLength(text, text.length + 999)

    expect(first).toBeGreaterThan(0)
    expect(second).toBeGreaterThan(first)
    expect(second).toBeLessThanOrEqual(text.length)
    expect(done).toBe(text.length)
  })

  test('buildEvidenceStats summarizes score and source coverage objectively', () => {
    const stats = buildEvidenceStats([
      { paper_id: 'p1', paper_source: 'Paper A', score: 0.91, start_line: 10, end_line: 22 },
      { paper_id: 'p1', paper_source: 'Paper A', score: 0.72, start_line: 40, end_line: 48 },
      { paper_id: 'p2', paper_source: 'Paper B', score: 0.55, start_line: 4, end_line: 9 },
      { paper_id: 'p3', paper_source: 'Paper C', score: undefined },
    ])

    expect(stats.total).toBe(4)
    expect(stats.scored).toBe(3)
    expect(stats.paperCount).toBe(3)
    expect(stats.sourceCount).toBe(3)
    expect(stats.avgScore).toBeCloseTo((0.91 + 0.72 + 0.55) / 3, 6)
    expect(stats.maxScore).toBeCloseTo(0.91, 6)
    expect(stats.lineStart).toBe(4)
    expect(stats.lineEnd).toBe(48)
    expect(stats.topSources[0]?.key).toBe('Paper A')
    expect(stats.topSources[0]?.count).toBe(2)
    expect(stats.scoreBuckets.reduce((sum, row) => sum + row.count, 0)).toBe(3)
  })
})
