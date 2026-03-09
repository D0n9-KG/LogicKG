import { describe, expect, test } from 'vitest'

import { buildNodeAskQuestion } from '../src/nodeAskPrompt'

describe('buildNodeAskQuestion', () => {
  test('paper prompt stays generic instead of appending raw paper labels', () => {
    expect(buildNodeAskQuestion('paper', '05_340', 'zh-CN')).toBe('请围绕这篇论文提炼核心方法、关键结论，并标出可核验的证据。')
    expect(buildNodeAskQuestion('paper', '05_340', 'en-US')).toBe(
      "Summarize this paper's core methods, key findings, and verifiable evidence.",
    )
  })

  test('logic prompts still keep explicit node labels', () => {
    expect(buildNodeAskQuestion('logic', 'Step A', 'zh-CN')).toContain('Step A')
    expect(buildNodeAskQuestion('claim', 'Claim B', 'en-US')).toContain('Claim B')
  })
})
