import { describe, expect, test } from 'vitest'

import {
  buildFitAllCameraTarget,
  buildGraph3DSceneConfig,
  buildGraph3DViewConfig,
  buildNodeFocusCameraTarget,
} from '../src/components/graph3dModel'

describe('graph3dModel', () => {
  test('buildGraph3DViewConfig allows much farther zoom-out for dense overview graphs', () => {
    const sparse = buildGraph3DViewConfig(20, 180)
    const dense = buildGraph3DViewConfig(540, 1200)

    expect(dense.autoFitPadding).toBeGreaterThanOrEqual(160)
    expect(dense.minDistance).toBeGreaterThanOrEqual(96)
    expect(dense.maxDistance).toBeGreaterThanOrEqual(9000)
    expect(dense.maxDistance).toBeGreaterThan(sparse.maxDistance)
  })

  test('buildFitAllCameraTarget centers on the graph bounds instead of the world origin', () => {
    const target = buildFitAllCameraTarget(
      {
        x: [420, 980],
        y: [-220, 140],
        z: [-90, 210],
      },
      { aspect: 1.6, fovDeg: 40, minDistance: 120 },
    )

    expect(target.lookAt.x).toBe(700)
    expect(target.lookAt.y).toBe(-40)
    expect(target.lookAt.z).toBe(60)
    expect(target.position.x).toBe(target.lookAt.x)
    expect(target.position.y).toBe(target.lookAt.y)
    expect(target.position.z).toBeGreaterThan(target.lookAt.z + 650)
  })

  test('buildGraph3DSceneConfig softens fog for dense overview graphs viewed from far away', () => {
    const compact = buildGraph3DSceneConfig(20, 220, 920)
    const denseFar = buildGraph3DSceneConfig(540, 5000, 8200)

    expect(denseFar.fogDensity).toBeLessThan(compact.fogDensity)
    expect(denseFar.fogDensity).toBeLessThanOrEqual(0.00008)
    expect(compact.fogDensity).toBeGreaterThanOrEqual(0.00012)
  })

  test('buildNodeFocusCameraTarget positions camera in front of selected node', () => {
    const target = buildNodeFocusCameraTarget({ x: 10, y: -20, z: 30, val: 8 })

    expect(target.lookAt).toEqual({ x: 10, y: -20, z: 30 })
    expect(target.position.z).toBeGreaterThan(target.lookAt.z)
    expect(target.position.x).toBe(10)
    expect(target.position.y).toBe(-20)
  })
})
