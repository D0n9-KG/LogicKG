import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'

vi.mock('../src/api', () => ({
  apiGet: vi.fn(async () => ({ ok: true })),
}))

import TopBar from '../src/components/TopBar'
import { I18nProvider } from '../src/i18n'
import { GlobalStateProvider } from '../src/state/store'

describe('TopBar navigation', () => {
  beforeEach(() => {
    window.localStorage.setItem('logickg.ui.locale.v1', 'en-US')
  })

  test('does not show discovery in module navigation', async () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <GlobalStateProvider>
            <TopBar />
          </GlobalStateProvider>
        </I18nProvider>
      </MemoryRouter>,
    )

    await screen.findByTitle(/API Status: ok/i)
    expect(screen.queryByText('Discovery')).not.toBeInTheDocument()
    expect(screen.getByText('Ops')).toBeInTheDocument()
  })
})
