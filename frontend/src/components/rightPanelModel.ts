export type RelationRow = {
  kind: string
  label: string
  count: number
}

export type NodeContentState = {
  full: string
  preview: string
  truncated: boolean
}

export type EvidenceRow = {
  paper_id?: string
  paper_source?: string
  paper_title?: string
  md_path?: string
  start_line?: number
  end_line?: number
  score?: number
  snippet?: string
}

type BuildNodeContentArgs = {
  label?: unknown
  description?: unknown
  maxChars?: number
}

function normalizeText(value: unknown): string {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
}

function safeMaxChars(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return 220
  return Math.max(60, Math.min(800, Math.round(n)))
}

export function buildNodeContentState(args: BuildNodeContentArgs): NodeContentState {
  const full = normalizeText(args.description) || normalizeText(args.label)
  const maxChars = safeMaxChars(args.maxChars)
  if (full.length <= maxChars) {
    return {
      full,
      preview: full,
      truncated: false,
    }
  }
  return {
    full,
    preview: `${full.slice(0, maxChars).trimEnd()}...`,
    truncated: true,
  }
}

export function rankRelationRows(rows: RelationRow[], limit = 8): RelationRow[] {
  const cap = Math.max(1, Math.min(30, Math.round(limit)))
  return [...rows]
    .filter((row) => Number.isFinite(row.count) && row.count > 0)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, cap)
}

export function filterEvidenceRows(rows: EvidenceRow[], query: string, limit = 16): EvidenceRow[] {
  const cap = Math.max(1, Math.min(200, Math.round(limit)))
  const normalizedQuery = normalizeText(query).toLowerCase()
  const filtered = normalizedQuery
    ? rows.filter((row) =>
        [row.paper_title, row.paper_id, row.paper_source, row.md_path, row.snippet]
          .map((field) => normalizeText(field).toLowerCase())
          .some((field) => field.includes(normalizedQuery)),
      )
    : rows

  return [...filtered]
    .sort((a, b) => {
      const scoreA = Number(a.score)
      const scoreB = Number(b.score)
      const safeA = Number.isFinite(scoreA) ? scoreA : -Infinity
      const safeB = Number.isFinite(scoreB) ? scoreB : -Infinity
      if (safeA !== safeB) return safeB - safeA

      const keyA =
        normalizeText(a.paper_title) || normalizeText(a.paper_source) || normalizeText(a.paper_id) || normalizeText(a.md_path)
      const keyB =
        normalizeText(b.paper_title) || normalizeText(b.paper_source) || normalizeText(b.paper_id) || normalizeText(b.md_path)
      return keyA.localeCompare(keyB)
    })
    .slice(0, cap)
}
