import type { UILocale } from './i18n'

function normalize(value: unknown): string {
  return String(value ?? '').trim()
}

export function buildNodeAskQuestion(nodeKind: string, nodeLabel: string, locale: UILocale): string {
  const kind = normalize(nodeKind).toLowerCase()
  const label = normalize(nodeLabel)

  if (kind === 'paper') {
    return locale === 'zh-CN'
      ? '请围绕这篇论文提炼核心方法、关键结论，并标出可核验的证据。'
      : "Summarize this paper's core methods, key findings, and verifiable evidence."
  }
  if (kind === 'logic') {
    return locale === 'zh-CN'
      ? `请解释该逻辑步骤在论文中的作用、证据来源与局限：${label}`
      : `Explain this logic step in the paper, including role, evidence sources, and limitations: ${label}`
  }
  if (kind === 'claim') {
    return locale === 'zh-CN'
      ? `请评估该论断的证据充分性与可验证性：${label}`
      : `Assess this claim for evidence sufficiency and verifiability: ${label}`
  }
  return locale === 'zh-CN'
    ? `请基于该节点给出解释，并梳理证据链：${label}`
    : `Explain this node and outline its evidence chain: ${label}`
}
