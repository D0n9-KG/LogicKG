export type HighlightLineRange = {
  start: number
  end: number
}

export type HighlightedMarkdownSegments = {
  before: string
  highlight: string
  after: string
}

type DisplayMathBlock = {
  start: number
  end: number
}

function isEscaped(text: string, index: number) {
  let backslashCount = 0
  for (let i = index - 1; i >= 0 && text[i] === '\\'; i -= 1) backslashCount += 1
  return backslashCount % 2 === 1
}

function countDisplayMathDelimiters(line: string) {
  let count = 0
  for (let i = 0; i < line.length - 1; i += 1) {
    if (line[i] !== '$' || line[i + 1] !== '$' || isEscaped(line, i)) continue
    count += 1
    i += 1
  }
  return count
}

function findDisplayMathBlocks(lines: string[]) {
  const blocks: DisplayMathBlock[] = []
  let openStart: number | null = null

  lines.forEach((line, index) => {
    const delimiterCount = countDisplayMathDelimiters(line)
    if (delimiterCount === 0) return
    if (openStart === null) {
      if (delimiterCount % 2 === 1) openStart = index
      return
    }
    if (delimiterCount % 2 === 1) {
      blocks.push({ start: openStart, end: index + 1 })
      openStart = null
    }
  })

  return blocks
}

function clampLineNumber(value: number, max: number, fallback: number) {
  if (!Number.isFinite(value)) return fallback
  return Math.max(1, Math.min(max, Math.trunc(value)))
}

export function splitOriginalTextForHighlight(
  content: string,
  highlightRange: HighlightLineRange | null | undefined,
): HighlightedMarkdownSegments | null {
  if (!content || !highlightRange) return null

  const lines = content.split('\n')
  if (lines.length === 0) return null

  const rawStart = clampLineNumber(highlightRange.start, lines.length, 1)
  const rawEnd = clampLineNumber(highlightRange.end, lines.length, rawStart)

  let start = Math.min(rawStart, rawEnd) - 1
  let end = Math.max(rawStart, rawEnd)

  for (const block of findDisplayMathBlocks(lines)) {
    if (start > block.start && start < block.end) start = block.start
    if (end > block.start && end < block.end) end = block.end
  }

  return {
    before: lines.slice(0, start).join('\n'),
    highlight: lines.slice(start, end).join('\n'),
    after: lines.slice(end).join('\n'),
  }
}
