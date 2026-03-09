import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'

import MarkdownView from '../src/components/MarkdownView'
import { splitOriginalTextForHighlight } from '../src/pages/originalTextHighlight'

const SAMPLE_MARKDOWN = [
  'Intro paragraph.',
  '$$',
  '\\mathbf{F} = m a',
  '\\int_0^1 x^2 \\, dx',
  '$$',
  'Conclusion paragraph.',
].join('\n')

describe('splitOriginalTextForHighlight', () => {
  test('expands a highlight that intersects a display-math block', () => {
    const segments = splitOriginalTextForHighlight(SAMPLE_MARKDOWN, { start: 3, end: 3 })

    expect(segments).toEqual({
      before: 'Intro paragraph.',
      highlight: ['$$', '\\mathbf{F} = m a', '\\int_0^1 x^2 \\, dx', '$$'].join('\n'),
      after: 'Conclusion paragraph.',
    })
  })

  test('keeps display math renderable after splitting', () => {
    const segments = splitOriginalTextForHighlight(SAMPLE_MARKDOWN, { start: 3, end: 3 })
    expect(segments).not.toBeNull()

    const html = renderToStaticMarkup(createElement(MarkdownView, { markdown: segments!.highlight, paperId: 'paper-1' }))

    expect(html).toContain('katex-display')
    expect(html).not.toContain('$$')
  })

  test('does not expand highlights outside display-math blocks', () => {
    const segments = splitOriginalTextForHighlight(SAMPLE_MARKDOWN, { start: 1, end: 1 })

    expect(segments).toEqual({
      before: '',
      highlight: 'Intro paragraph.',
      after: ['$$', '\\mathbf{F} = m a', '\\int_0^1 x^2 \\, dx', '$$', 'Conclusion paragraph.'].join('\n'),
    })
  })
})
