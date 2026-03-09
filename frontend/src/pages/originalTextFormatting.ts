import { normalizeFormulaBody } from '../components/markdownMath'

type FormattedBlock = {
  kind: 'prose' | 'math' | 'verbatim'
  text: string
}

function isDisplayMathDelimiter(line: string): boolean {
  return line.trim() === '$$'
}

function isSpecialBlockLine(line: string): boolean {
  const trimmed = line.trim()
  return /^(#{1,6}\s|>|\* |\+ |- |\d+[.)]\s|```|~~~|!\[|<)/.test(trimmed) || /^\|.*\|$/.test(trimmed)
}

function reflowLines(lines: string[]): string {
  return lines
    .map((line) => line.trim())
    .filter(Boolean)
    .reduce((merged, line) => {
      if (!merged) return line
      if (merged.endsWith('-') && /^[A-Za-z]/.test(line)) return `${merged.slice(0, -1)}${line}`
      return `${merged} ${line}`
    }, '')
}

function shouldMergeProseBlocks(previous: string, next: string): boolean {
  const prev = previous.trim()
  const nxt = next.trim()
  if (!prev || !nxt) return false
  if (/[.!?。！？:：;；)]$/.test(prev)) return false
  if (isSpecialBlockLine(nxt)) return false
  return /^[a-z0-9([\\$]/.test(nxt)
}

function parseBlocks(markdown: string): string[][] {
  const lines = String(markdown ?? '').replace(/\r\n?/g, '\n').split('\n')
  const blocks: string[][] = []
  let current: string[] = []
  let inDisplayMath = false

  const flush = () => {
    if (current.length > 0) blocks.push(current)
    current = []
  }

  for (const line of lines) {
    if (isDisplayMathDelimiter(line)) {
      if (!inDisplayMath) flush()
      current.push('$$')
      if (inDisplayMath) {
        flush()
        inDisplayMath = false
      } else {
        inDisplayMath = true
      }
      continue
    }

    if (inDisplayMath) {
      current.push(line)
      continue
    }

    if (!line.trim()) {
      flush()
      continue
    }

    current.push(line)
  }

  flush()
  return blocks
}

function formatBlock(lines: string[]): FormattedBlock {
  if (lines.length >= 2 && isDisplayMathDelimiter(lines[0]) && isDisplayMathDelimiter(lines[lines.length - 1])) {
    const body = normalizeFormulaBody(lines.slice(1, -1).join('\n'))
    return {
      kind: 'math',
      text: ['$$', body, '$$'].join('\n'),
    }
  }

  const trimmedLines = lines.map((line) => line.trim()).filter(Boolean)
  if (trimmedLines.length === 0) return { kind: 'prose', text: '' }

  if (trimmedLines.length === 1 && isSpecialBlockLine(trimmedLines[0])) {
    return { kind: 'verbatim', text: trimmedLines[0] }
  }

  if (trimmedLines.every((line) => /^\|.*\|$/.test(line))) {
    return { kind: 'verbatim', text: trimmedLines.join('\n') }
  }

  return {
    kind: 'prose',
    text: reflowLines(trimmedLines),
  }
}

export function formatOriginalTextMarkdown(markdown: string): string {
  const formattedBlocks = parseBlocks(markdown)
    .map((block) => formatBlock(block))
    .filter((block) => block.text.trim().length > 0)

  const merged: FormattedBlock[] = []
  for (const block of formattedBlocks) {
    const previous = merged[merged.length - 1]
    if (block.kind === 'prose' && previous?.kind === 'prose' && shouldMergeProseBlocks(previous.text, block.text)) {
      previous.text = previous.text.endsWith('-')
        ? `${previous.text.slice(0, -1)}${block.text}`
        : `${previous.text} ${block.text}`
      continue
    }
    merged.push({ ...block })
  }

  return merged.map((block) => block.text).join('\n\n')
}
