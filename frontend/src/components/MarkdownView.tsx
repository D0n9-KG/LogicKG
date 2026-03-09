import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkBreaks from 'remark-breaks'

import { apiBaseUrl } from '../api'
import { normalizeMathMarkdown } from './markdownMath'

type Props = {
  markdown: string
  paperId?: string
  className?: string
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
