import { describe, expect, test } from 'vitest'

import { CHUNK_SIZE_WARNING_LIMIT, resolveManualChunk } from '../config/viteChunking'

describe('vite chunking strategy', () => {
  test('keeps React runtime and router in a dedicated vendor chunk', () => {
    expect(resolveManualChunk('/repo/node_modules/react/index.js')).toBe('react-vendor')
    expect(resolveManualChunk('/repo/node_modules/react-dom/client.js')).toBe('react-vendor')
    expect(resolveManualChunk('/repo/node_modules/react-router-dom/dist/index.js')).toBe('react-vendor')
  })

  test('splits graph and markdown heavy dependencies into dedicated chunks', () => {
    expect(resolveManualChunk('/repo/node_modules/cytoscape/dist/cytoscape.esm.mjs')).toBe('graph2d-vendor')
    expect(resolveManualChunk('/repo/node_modules/3d-force-graph/dist/3d-force-graph.mjs')).toBe('graph3d-vendor')
    expect(resolveManualChunk('/repo/node_modules/three/build/three.module.js')).toBe('three-vendor')
    expect(resolveManualChunk('/repo/node_modules/react-markdown/index.js')).toBe('markdown-vendor')
    expect(resolveManualChunk('/repo/node_modules/remark-gfm/index.js')).toBe('markdown-vendor')
    expect(resolveManualChunk('/repo/node_modules/katex/dist/katex.mjs')).toBe('markdown-vendor')
  })

  test('leaves application source files to Rollup defaults', () => {
    expect(resolveManualChunk('/repo/src/components/GraphCanvas.tsx')).toBeUndefined()
  })

  test('raises the warning threshold to reflect the isolated lazy 3D vendor chunk', () => {
    expect(CHUNK_SIZE_WARNING_LIMIT).toBe(1200)
  })
})
