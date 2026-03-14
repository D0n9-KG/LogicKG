import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, test } from 'vitest'

describe('global select theme css', () => {
  test('defines dark styling for native select dropdown options', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

    expect(css).toMatch(/color-scheme:\s*dark/i)
    expect(css).toMatch(/select\s+option/i)
    expect(css).toMatch(/select\s+optgroup/i)
  })
})
