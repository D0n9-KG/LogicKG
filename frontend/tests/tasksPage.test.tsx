import { describe, expect, test, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('../src/i18n', async () => {
  const actual = await vi.importActual<typeof import('../src/i18n')>('../src/i18n')
  return {
    ...actual,
    useI18n: () => ({
      locale: 'en-US',
      t: (_zh: string, en: string) => en,
    }),
  }
})

import TasksPage from '../src/pages/TasksPage'

describe('TasksPage', () => {
  test('does not render evolution rebuild copy or actions', () => {
    const html = renderToStaticMarkup(<TasksPage />)

    expect(html).not.toContain('Recompute Evolution')
    expect(html).not.toContain('Backend queue tasks (ingest / replace / rebuild / evolution)')
  })
})
