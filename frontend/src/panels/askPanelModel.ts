import type { AskItem } from '../state/types'

export type AskUiLocale = 'zh-CN' | 'en-US'

export type ScopePaperApiRow = {
  id: string
  label: string
  year?: number
}

export type ScopePaperOption = {
  id: string
  label: string
  year?: number
  source: 'api'
}

export type ConversationTurn = AskItem & {
  active: boolean
}

export type ChatMessage = {
  id: string
  turnId: string
  role: 'user' | 'assistant'
  text: string
  createdAt: number
  k: number
  status: AskItem['status']
  active: boolean
  markdown: boolean
}

export type AskScopeMode = 'all' | 'collection' | 'papers'

export type AskResponseLike = {
  answer?: unknown
  insufficient_scope_evidence?: unknown
}

export type EvidenceLike = {
  paper_id?: unknown
  paper_source?: unknown
  paper_title?: unknown
  start_line?: unknown
  end_line?: unknown
  score?: unknown
}

export type EvidenceSourceSummary = {
  key: string
  count: number
  avgScore: number | null
  maxScore: number | null
}

export type EvidenceScoreBucket = {
  key: 'high' | 'mid' | 'low' | 'tail'
  label: string
  count: number
}

export type EvidenceStats = {
  total: number
  scored: number
  avgScore: number | null
  maxScore: number | null
  sourceCount: number
  paperCount: number
  lineStart: number | null
  lineEnd: number | null
  topSources: EvidenceSourceSummary[]
  scoreBuckets: EvidenceScoreBucket[]
}

function normalize(value: unknown): string {
  return String(value ?? '').trim()
}

function normalizeYear(value: unknown): number | undefined {
  const year = Number(value)
  if (!Number.isFinite(year)) return undefined
  if (year < 1900 || year > 2100) return undefined
  return Math.round(year)
}

function toLineNumber(value: unknown): number | null {
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  const rounded = Math.round(n)
  return rounded > 0 ? rounded : null
}

function toScore(value: unknown): number | null {
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return n
}

function scoreAverage(values: number[]): number | null {
  if (!values.length) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function comparePaperOption(a: ScopePaperOption, b: ScopePaperOption): number {
  const ay = a.year ?? -1
  const by = b.year ?? -1
  if (by !== ay) return by - ay
  return a.label.localeCompare(b.label)
}

export function buildScopePaperOptions(apiRows: ScopePaperApiRow[]): ScopePaperOption[] {
  const map = new Map<string, ScopePaperOption>()

  for (const row of apiRows) {
    const id = normalize(row.id)
    if (!id) continue
    const current = map.get(id)
    const nextLabel = normalize(row.label) || current?.label || id
    const nextYear = normalizeYear(row.year) ?? current?.year
    map.set(id, {
      id,
      label: nextLabel,
      year: nextYear,
      source: 'api',
    })
  }

  return Array.from(map.values()).sort(comparePaperOption)
}

export function toggleScopePaperIds(currentIds: string[], paperId: string): string[] {
  const normalizedId = normalize(paperId)
  if (!normalizedId) return []
  const uniq = Array.from(new Set(currentIds.map((id) => normalize(id)).filter(Boolean)))
  if (uniq.includes(normalizedId)) {
    return uniq.filter((id) => id !== normalizedId)
  }
  return [...uniq, normalizedId].sort((a, b) => a.localeCompare(b))
}

export function toConversationTurns(history: AskItem[], currentId: string | null): ConversationTurn[] {
  const turns = [...history].sort((a, b) => {
    if (a.createdAt !== b.createdAt) return a.createdAt - b.createdAt
    return a.id.localeCompare(b.id)
  })
  const activeId = currentId ?? turns[turns.length - 1]?.id ?? null
  return turns.map((item) => ({
    ...item,
    active: item.id === activeId,
  }))
}

export function buildChatMessages(turns: ConversationTurn[], locale: AskUiLocale = 'zh-CN'): ChatMessage[] {
  const messages: ChatMessage[] = []
  for (const turn of turns) {
    messages.push({
      id: `${turn.id}:user`,
      turnId: turn.id,
      role: 'user',
      text: normalize(turn.question),
      createdAt: turn.createdAt,
      k: turn.k,
      status: turn.status,
      active: turn.active,
      markdown: false,
    })

    const assistantText = assistantTurnText(turn, locale)
    messages.push({
      id: `${turn.id}:assistant`,
      turnId: turn.id,
      role: 'assistant',
      text: assistantText,
      createdAt: turn.createdAt,
      k: turn.k,
      status: turn.status,
      active: turn.active,
      markdown: turn.status === 'done' && normalize(turn.answer).length > 0,
    })
  }
  return messages
}

export function shouldAutoRetryWithAllScope(scopeMode: AskScopeMode, response: AskResponseLike): boolean {
  if (scopeMode === 'all') return false
  if (!response.insufficient_scope_evidence) return false
  return false
}

export function getScopePaperRenderState(options: ScopePaperOption[], limit: number): {
  visible: ScopePaperOption[]
  hasMore: boolean
  remaining: number
} {
  const safeLimit = Number.isFinite(limit) ? Math.max(1, Math.floor(limit)) : 1
  const visible = options.slice(0, safeLimit)
  const remaining = Math.max(0, options.length - visible.length)
  return {
    visible,
    hasMore: remaining > 0,
    remaining,
  }
}

export function nextStreamRevealLength(text: string, currentLength: number): number {
  const source = String(text ?? '')
  const total = source.length
  if (total === 0) return 0

  const current = Number.isFinite(currentLength) ? Math.max(0, Math.floor(currentLength)) : 0
  if (current >= total) return total

  const step = Math.max(3, Math.min(26, Math.ceil(total / 40)))
  let next = Math.min(total, current + step)
  const maxAdvance = Math.min(total, current + step * 2)
  while (next < maxAdvance && next < total) {
    const ch = source[next - 1]
    if (/[銆傦紒锛??锛?锛?锛?\n ]/.test(ch)) break
    next += 1
  }
  return Math.max(current + 1, Math.min(total, next))
}

export function buildEvidenceStats(rows: EvidenceLike[]): EvidenceStats {
  const scoreBuckets: EvidenceScoreBucket[] = [
    { key: 'high', label: '>=0.80', count: 0 },
    { key: 'mid', label: '0.60-0.79', count: 0 },
    { key: 'low', label: '0.40-0.59', count: 0 },
    { key: 'tail', label: '<0.40', count: 0 },
  ]

  const paperIds = new Set<string>()
  const sources = new Set<string>()
  const scoredValues: number[] = []
  let lineStart: number | null = null
  let lineEnd: number | null = null

  const sourceMap = new Map<string, { count: number; scores: number[] }>()

  for (const row of rows) {
    const paperId = normalize(row.paper_id)
    const paperTitle = normalize(row.paper_title)
    const source = normalize(row.paper_source)
    const sourceKey = paperTitle || source || paperId || 'unknown'

    if (paperId) paperIds.add(paperId)
    if (sourceKey) sources.add(sourceKey)

    const sourceRow = sourceMap.get(sourceKey) ?? { count: 0, scores: [] }
    sourceRow.count += 1

    const score = toScore(row.score)
    if (score !== null) {
      scoredValues.push(score)
      sourceRow.scores.push(score)

      if (score >= 0.8) scoreBuckets[0].count += 1
      else if (score >= 0.6) scoreBuckets[1].count += 1
      else if (score >= 0.4) scoreBuckets[2].count += 1
      else scoreBuckets[3].count += 1
    }

    const startLine = toLineNumber(row.start_line)
    const endLine = toLineNumber(row.end_line)
    const rowStart = startLine ?? endLine
    const rowEnd = endLine ?? startLine
    if (rowStart !== null) lineStart = lineStart === null ? rowStart : Math.min(lineStart, rowStart)
    if (rowEnd !== null) lineEnd = lineEnd === null ? rowEnd : Math.max(lineEnd, rowEnd)

    sourceMap.set(sourceKey, sourceRow)
  }

  const topSources: EvidenceSourceSummary[] = Array.from(sourceMap.entries())
    .map(([key, info]) => ({
      key,
      count: info.count,
      avgScore: scoreAverage(info.scores),
      maxScore: info.scores.length ? Math.max(...info.scores) : null,
    }))
    .sort((a, b) => b.count - a.count || (b.avgScore ?? -1) - (a.avgScore ?? -1) || a.key.localeCompare(b.key))
    .slice(0, 8)

  return {
    total: rows.length,
    scored: scoredValues.length,
    avgScore: scoreAverage(scoredValues),
    maxScore: scoredValues.length ? Math.max(...scoredValues) : null,
    sourceCount: sources.size,
    paperCount: paperIds.size,
    lineStart,
    lineEnd,
    topSources,
    scoreBuckets,
  }
}

export function assistantTurnText(
  item: Pick<AskItem, 'status' | 'answer' | 'notice' | 'error'>,
  locale: AskUiLocale = 'zh-CN',
): string {
  if (item.status === 'running') {
    const answer = normalize(item.answer)
    if (answer) return answer
    return locale === 'zh-CN' ? '正在检索与推理...' : 'Searching evidence and reasoning...'
  }
  if (item.status === 'error') return normalize(item.error) || (locale === 'zh-CN' ? '请求失败' : 'Request failed')
  const answer = normalize(item.answer)
  if (answer) return answer
  const notice = normalize(item.notice)
  if (notice) return notice
  return locale === 'zh-CN'
    ? '暂无可用结果，请尝试扩大全图范围后重试。'
    : 'No usable result yet. Try expanding to the full graph and retry.'
}

