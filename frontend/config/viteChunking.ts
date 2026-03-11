// The remaining large chunk is the intentionally lazy-loaded three.js runtime.
// Keeping the threshold explicit avoids noisy warnings while still flagging
// unexpected growth in the eager application chunks.
export const CHUNK_SIZE_WARNING_LIMIT = 1200

const REACT_VENDOR_PATTERNS = [
  '/node_modules/react/',
  '/node_modules/react-dom/',
  '/node_modules/react-router/',
  '/node_modules/react-router-dom/',
  '/node_modules/scheduler/',
]

const GRAPH2D_VENDOR_PATTERNS = ['/node_modules/cytoscape/']

const GRAPH3D_VENDOR_PATTERNS = ['/node_modules/3d-force-graph/']

const THREE_VENDOR_PATTERNS = ['/node_modules/three/']

const MARKDOWN_VENDOR_PATTERNS = [
  '/node_modules/react-markdown/',
  '/node_modules/remark-',
  '/node_modules/rehype-',
  '/node_modules/katex/',
  '/node_modules/unified/',
  '/node_modules/unist',
  '/node_modules/micromark',
  '/node_modules/mdast',
  '/node_modules/hast',
  '/node_modules/vfile',
  '/node_modules/property-information/',
  '/node_modules/space-separated-tokens/',
  '/node_modules/comma-separated-tokens/',
  '/node_modules/html-url-attributes/',
  '/node_modules/devlop/',
  '/node_modules/bail/',
  '/node_modules/trough/',
  '/node_modules/zwitch/',
  '/node_modules/ccount/',
  '/node_modules/parse-entities/',
  '/node_modules/stringify-entities/',
  '/node_modules/character-entities',
  '/node_modules/decode-named-character-reference/',
]

function normalizeId(id: string): string {
  return id.replace(/\\/g, '/')
}

function matchesAny(id: string, patterns: string[]): boolean {
  return patterns.some((pattern) => id.includes(pattern))
}

export function resolveManualChunk(id: string): string | undefined {
  const normalizedId = normalizeId(id)
  if (!normalizedId.includes('/node_modules/')) return undefined
  if (matchesAny(normalizedId, GRAPH3D_VENDOR_PATTERNS)) return 'graph3d-vendor'
  if (matchesAny(normalizedId, THREE_VENDOR_PATTERNS)) return 'three-vendor'
  if (matchesAny(normalizedId, GRAPH2D_VENDOR_PATTERNS)) return 'graph2d-vendor'
  if (matchesAny(normalizedId, MARKDOWN_VENDOR_PATTERNS)) return 'markdown-vendor'
  if (matchesAny(normalizedId, REACT_VENDOR_PATTERNS)) return 'react-vendor'
  return 'vendor'
}
