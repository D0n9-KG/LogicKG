import { describe, expect, test } from 'vitest'

import { orientComponentPositions, placeOverviewComponents } from '../src/components/paperOverviewLayout'

describe('paperOverviewLayout', () => {
  test('rotates tall component positions to favor a wider silhouette', () => {
    const positions = new Map([
      ['n1', { x: 0, y: 0 }],
      ['n2', { x: 6, y: 120 }],
      ['n3', { x: -4, y: 240 }],
      ['n4', { x: 5, y: 360 }],
    ])

    const oriented = orientComponentPositions(positions)
    const xs = [...oriented.values()].map((point) => point.x)
    const ys = [...oriented.values()].map((point) => point.y)
    const width = Math.max(...xs) - Math.min(...xs)
    const height = Math.max(...ys) - Math.min(...ys)

    expect(width).toBeGreaterThan(height)
  })

  test('keeps the focus component centered and pushes other components into an orbit', () => {
    const placements = placeOverviewComponents([
      { id: 'focus', width: 900, height: 680, weight: 28 },
      { id: 'beta', width: 420, height: 320, weight: 10 },
      { id: 'gamma', width: 380, height: 300, weight: 8 },
      { id: 'delta', width: 280, height: 220, weight: 4 },
    ], 'focus')

    const focus = placements.get('focus')
    const beta = placements.get('beta')
    const gamma = placements.get('gamma')
    const delta = placements.get('delta')

    expect(focus).toBeDefined()
    expect(beta).toBeDefined()
    expect(gamma).toBeDefined()
    expect(delta).toBeDefined()
    expect(Math.abs(focus?.x ?? 999)).toBeLessThan(1)
    expect(Math.abs(focus?.y ?? 999)).toBeLessThan(1)
    expect(Math.hypot(beta?.x ?? 0, beta?.y ?? 0)).toBeGreaterThan(600)
    expect(Math.hypot(gamma?.x ?? 0, gamma?.y ?? 0)).toBeGreaterThan(600)
    expect(Math.hypot(delta?.x ?? 0, delta?.y ?? 0)).toBeGreaterThan(600)
    expect(new Set([beta?.y, gamma?.y, delta?.y]).size).toBeGreaterThan(1)
  })

  test('shrinks non-focus components so the main knowledge island stays dominant', () => {
    const placements = placeOverviewComponents([
      { id: 'focus', width: 960, height: 720, weight: 30 },
      { id: 'beta', width: 520, height: 360, weight: 12 },
      { id: 'gamma', width: 260, height: 200, weight: 3 },
    ], 'focus')

    const focus = placements.get('focus')
    const beta = placements.get('beta')
    const gamma = placements.get('gamma')

    expect(focus?.scale).toBe(1)
    expect((beta?.scale ?? 1)).toBeLessThan(1)
    expect((gamma?.scale ?? 1)).toBeLessThan((beta?.scale ?? 1))
  })
})
