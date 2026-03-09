const STRUCTURAL_MARKDOWN_RE = /^\s{0,3}(?:#{1,6}\s|>|\* |\+ |- |\d+[.)]\s|```|~~~|!\[|\|)|^\s*---\s*$/m

export function compactLatexCommands(text: string): string {
  return text.replace(/\\(?:[a-zA-Z](?:\s+[a-zA-Z])+)/g, (raw) => {
    return `\\${raw.slice(1).replace(/\s+/g, '')}`
  })
}

export function normalizeFormulaBody(raw: string): string {
  return compactLatexCommands(String(raw ?? '').trim())
    .replace(/([_^])\s+\{/g, '$1{')
    .replace(/\\tag\s+\{/g, '\\tag{')
    .replace(/\\left\s+([()[\]{}|<>])/g, '\\left$1')
    .replace(/\\right\s+([()[\]{}|<>])/g, '\\right$1')
    .replace(/[ \t]{2,}/g, ' ')
    .trim()
}

function looksLikeStandaloneFormula(text: string): boolean {
  const t = String(text ?? '').trim()
  if (!t) return false
  if (/\n\s*\n/.test(t)) return false
  if (STRUCTURAL_MARKDOWN_RE.test(t)) return false

  const nonEmptyLines = t
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  if (nonEmptyLines.length > 3) return false

  const flat = nonEmptyLines.join(' ')
  const commandCount = (flat.match(/\\[a-zA-Z]+/g) ?? []).length
  const symbolicCount = (flat.match(/[_^{}=]/g) ?? []).length
  const longWordCount = (flat.match(/[A-Za-z]{4,}/g) ?? []).length
  const sentencePunctuationCount = (flat.match(/[.!?。！？]/g) ?? []).length

  if (/\n/.test(t) && !/[=<>±∑∫]/.test(flat)) return false
  if (sentencePunctuationCount > 1 && commandCount < 6) return false

  return (commandCount >= 2 && symbolicCount >= 5) || (commandCount >= 4 && longWordCount <= 10)
}

function normalizeFormulaText(raw: string): string {
  let t = String(raw ?? '').trim()
  if (!t) return ''

  const singleInline = t.match(/^\$([^$\n]+)\$$/)
  if (singleInline && /\\tag\s*\{[^}]+\}/.test(singleInline[1])) {
    return `$$\n${normalizeFormulaBody(singleInline[1])}\n$$`
  }

  t = normalizeFormulaBody(t)
  if (!/\$/.test(t) && looksLikeStandaloneFormula(t)) {
    t = `$$\n${t}\n$$`
  }
  return t
}

function promoteTaggedInlineMath(markdown: string): string {
  const source = String(markdown ?? '')
  if (!source.includes('$') || !/\\tag\s*\{[^}]+\}/.test(source)) return source

  return source.replace(/\$([^$\n]+)\$/g, (raw, body: string) => {
    if (!/\\tag\s*\{[^}]+\}/.test(body)) return raw
    const normalized = normalizeFormulaBody(body)
    if (!normalized) return raw
    return `\n$$\n${normalized}\n$$\n`
  })
}

export function normalizeMathMarkdown(markdown: string): string {
  const source = String(markdown ?? '')
  if (!source.trim()) return ''

  const promoted = promoteTaggedInlineMath(source)
  const trimmed = promoted.trim()
  const isSingleMathBlock = /^\$\$[\s\S]*\$\$$/.test(trimmed) || /^\$[^$\n]+\$$/.test(trimmed)

  if (isSingleMathBlock || looksLikeStandaloneFormula(promoted)) {
    return normalizeFormulaText(promoted)
  }

  return promoted
}
