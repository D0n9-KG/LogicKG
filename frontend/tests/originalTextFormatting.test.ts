import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'

import MarkdownView from '../src/components/MarkdownView'
import { formatOriginalTextMarkdown } from '../src/pages/originalTextFormatting'

const RAW_SOURCE = [
  'Finite element simulations at the particle scale were performed by Mesarovic and Fleck (1999, 2000). Mesarovic and Fleck (2000) also carried out a finite element study of a periodic structure. The first MDEM studies on granular random packings were done in 2D (Gethin et al., 2003; Procopio and Zavaliangos, 2005). Then',
  '',
  'the problem of 3D packings has been analyzed in particular by Chen et al. (2006); Frenning (2008) and Chen (2008). The MDEM gives an accurate description of the particles\' deformation and produce accurate results up to high densities. Unfortunately, because of its high computational cost, this type of simulation is limited to assemblies of about a hundred particles.',
  '',
  'Thus, this approach consists in analyzing the densification of a simple cubic lattice by using MDEM simulations. Fig. 1 summarizes this approach.',
  '',
  '# 2. Material',
  '',
  'An elastic-plastic Von Mises-type constitutive law with strain hardening is used to represent the spheres\' material. The relationship between stress and strain in the uniaxial case is given by:',
  '',
  '$$',
  '\\sigma = \\sigma_ {Y} + K _ {1} \\varepsilon_ {p l} ^ {n _ {1}}, \\tag {1}',
  '$$',
  '',
  'where $\\sigma$ is the uniaxial stress, $\\sigma_{Y}$ the yield stress, $\\varepsilon_{pl}$ the equivalent plastic strain, and $K_{1}$ and $n_1$ are the hardening parameters.',
].join('\n')

describe('formatOriginalTextMarkdown', () => {
  test('merges wrapped prose paragraphs while preserving block boundaries', () => {
    const formatted = formatOriginalTextMarkdown(RAW_SOURCE)

    expect(formatted).toContain('Then the problem of 3D packings has been analyzed')
    expect(formatted).toContain('\n\n# 2. Material\n\n')
    expect(formatted).toContain('$$')
  })

  test('keeps section headings and display equations renderable', () => {
    const html = renderToStaticMarkup(
      createElement(MarkdownView, {
        markdown: formatOriginalTextMarkdown(RAW_SOURCE),
        paperId: 'paper-1',
      }),
    )

    expect(html).toContain('<h1>2. Material</h1>')
    expect(html).toContain('katex-display')
    expect(html).not.toContain('katex-error')
  })
})
