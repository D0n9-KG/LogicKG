import { describe, expect, test } from 'vitest'

import { buildOverview3DVisibleLinks, type Graph3DDisplayLink } from '../src/components/graph3dLinkBudget'

function makeLink(id: string, source: string, target: string, weight: number, kind = 'similar'): Graph3DDisplayLink {
  return { id, source, target, kind, weight }
}

describe('graph3dLinkBudget', () => {
  test('keeps a bounded similar-edge skeleton by default', () => {
    const links = [
      makeLink('ab', 'community:a', 'community:b', 0.95),
      makeLink('ac', 'community:a', 'community:c', 0.9),
      makeLink('ad', 'community:a', 'community:d', 0.86),
      makeLink('ae', 'community:a', 'community:e', 0.8),
      makeLink('bc', 'community:b', 'community:c', 0.78),
      makeLink('bd', 'community:b', 'community:d', 0.74),
      makeLink('be', 'community:b', 'community:e', 0.69),
      makeLink('cd', 'community:c', 'community:d', 0.64),
      makeLink('ce', 'community:c', 'community:e', 0.59),
      makeLink('de', 'community:d', 'community:e', 0.42),
    ]

    const visible = buildOverview3DVisibleLinks(links)
    const visibleIds = new Set(visible.map((link) => link.id))

    expect(visible.filter((link) => link.kind === 'similar').length).toBe(links.length)
    expect(visible.filter((link) => link.kind === 'similar' && link.visible !== false).length).toBeLessThan(links.length)
    expect(visibleIds.has('ab')).toBe(true)
    expect(visibleIds.has('ac')).toBe(true)
    expect(visible.some((link) => link.id === 'ab' && link.emphasis === 'primary')).toBe(true)
    expect(visible.some((link) => link.id === 'ac' && link.emphasis === 'primary')).toBe(true)
    expect(visible.some((link) => link.id !== 'ab' && link.id !== 'ac' && link.emphasis === 'background')).toBe(true)
    expect(visible.some((link) => link.visible === false)).toBe(true)
  })

  test('restores all loaded similar edges for the selected community', () => {
    const links = [
      makeLink('ab', 'community:a', 'community:b', 0.95),
      makeLink('ac', 'community:a', 'community:c', 0.9),
      makeLink('ad', 'community:a', 'community:d', 0.86),
      makeLink('ae', 'community:a', 'community:e', 0.8),
      makeLink('bc', 'community:b', 'community:c', 0.78),
      makeLink('bd', 'community:b', 'community:d', 0.74),
      makeLink('ce', 'community:c', 'community:e', 0.59),
    ]

    const visible = buildOverview3DVisibleLinks(links, 'community:a')
    const visibleIds = new Set(visible.map((link) => link.id))

    expect(['ab', 'ac', 'ad', 'ae'].every((id) => visibleIds.has(id))).toBe(true)
    expect(
      visible
        .filter((link) => link.id === 'ab' || link.id === 'ac' || link.id === 'ad' || link.id === 'ae')
        .every((link) => link.emphasis === 'focus'),
    ).toBe(true)
    expect(
      visible
        .filter((link) => link.id === 'ab' || link.id === 'ac' || link.id === 'ad' || link.id === 'ae')
        .every((link) => link.visible !== false),
    ).toBe(true)
  })

  test('always preserves non-similar edges', () => {
    const links = [
      makeLink('ab', 'community:a', 'community:b', 0.95),
      makeLink('contain-a', 'community:a', 'claim:1', 0.92, 'contains'),
    ]

    const visible = buildOverview3DVisibleLinks(links)

    expect(visible).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: 'contain-a', kind: 'contains' }),
      ]),
    )
  })
})
