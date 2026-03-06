import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkBreaks from 'remark-breaks'

import { apiBaseUrl } from '../api'

type Props = {
  markdown: string
  paperId?: string
  className?: string
}

function looksLikeStandaloneFormula(text: string): boolean {
  const t = String(text ?? '').trim()
  if (!t) return false
  if (/\n/.test(t) && !/[=]/.test(t)) return false
  const commandCount = (t.match(/\\[a-zA-Z]+/g) ?? []).length
  const symbolicCount = (t.match(/[_^{}=]/g) ?? []).length
  const longWordCount = (t.match(/[A-Za-z]{4,}/g) ?? []).length
  return (commandCount >= 2 && symbolicCount >= 5) || (commandCount >= 4 && longWordCount <= 10)
}

function compactLatexCommands(text: string): string {
  return text.replace(/\\(?:[a-zA-Z](?:\s+[a-zA-Z])+)/g, (raw) => {
    return `\\${raw.slice(1).replace(/\s+/g, '')}`
  })
}

function normalizeFormulaText(raw: string): string {
  let t = String(raw ?? '').trim()
  if (!t) return ''

  t = compactLatexCommands(t)
  const singleInline = t.match(/^\$([^$\n]+)\$$/)
  if (singleInline && /\\tag\s*\{[^}]+\}/.test(singleInline[1])) {
    t = `$$\n${singleInline[1].trim()}\n$$`
  }
  t = t
    .replace(/([_^])\s+\{/g, '$1{')
    .replace(/\\tag\s+\{/g, '\\tag{')
    .replace(/\\left\s+([()[\]{}|<>])/g, '\\left$1')
    .replace(/\\right\s+([()[\]{}|<>])/g, '\\right$1')
    .replace(/\s{2,}/g, ' ')
    .trim()

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
    const normalized = normalizeFormulaText(body).trim()
    if (!normalized) return raw
    return `\n$$\n${normalized}\n$$\n`
  })
}

function normalizeMathMarkdown(markdown: string): string {
  const source = String(markdown ?? '')
  if (!source.trim()) return ''
  const promoted = promoteTaggedInlineMath(source)

  if (
    /^\s*(\$\$[\s\S]*\$\$|\$[^$\n]+\$)\s*$/.test(promoted.trim()) ||
    looksLikeStandaloneFormula(promoted)
  ) {
    return normalizeFormulaText(promoted)
  }

  return promoted
}

function encodePathSegments(path: string): string {
  return path
    .split('/')
    .filter((p) => p.length > 0)
    .map((p) => encodeURIComponent(p))
    .join('/')
}

function rewriteImageSrc(src: string, paperId?: string): string {
  const s = String(src ?? '').trim()
  if (!s) return ''
  if (/^(https?:|data:|blob:)/i.test(s)) return s

  const normalized = s.replace(/\\/g, '/').replace(/^\.\/+/, '')
  if (!paperId) return normalized

  if (normalized.startsWith('images/')) {
    const rel = normalized.slice('images/'.length)
    const base = apiBaseUrl()
    return `${base}/papers/${encodeURIComponent(paperId)}/images/${encodePathSegments(rel)}`
  }
  return normalized
}

function hasAnyScheme(url: string): boolean {
  return /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url)
}

function safeLinkHref(href: string): string {
  const s = String(href ?? '').trim()
  if (!s) return ''
  if (/^(https?:|mailto:|tel:)/i.test(s)) return s
  // Allow relative URLs, but block unknown schemes (javascript:, file:, etc.)
  if (hasAnyScheme(s)) return ''
  return s
}

function safeMediaSrc(src: string): string {
  const s = String(src ?? '').trim()
  if (!s) return ''
  if (/^(https?:|data:|blob:)/i.test(s)) return s
  if (hasAnyScheme(s)) return ''
  return s
}

export default function MarkdownView({ markdown, paperId, className }: Props) {
  const text = normalizeMathMarkdown(String(markdown ?? ''))
  return (
    <div className={`markdown ${className ?? ''}`.trim()}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks, remarkMath]}
        rehypePlugins={[rehypeRaw, [rehypeKatex, { throwOnError: false, strict: 'ignore' }]]}
        urlTransform={(url, key) => {
          if (key === 'href') return safeLinkHref(url)
          if (key === 'src') return rewriteImageSrc(safeMediaSrc(url), paperId)
          return url
        }}
        components={{
          a: ({ node, ...props }) => {
            void node
            const href = safeLinkHref(String(props.href ?? ''))
            if (!href) return <span>{props.children}</span>
            return <a {...props} href={href} target="_blank" rel="noreferrer" />
          },
          img: ({ node, ...props }) => {
            void node
            return (
            <img
              {...props}
              loading="lazy"
              decoding="async"
            />
            )
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}
