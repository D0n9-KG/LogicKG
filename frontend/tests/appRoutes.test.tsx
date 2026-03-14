import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, test, vi } from 'vitest'

vi.mock('../src/components/TopBar', () => ({
  default: () => <div>TopBar</div>,
}))

vi.mock('../src/components/StatusBar', () => ({
  default: () => <div>StatusBar</div>,
}))

vi.mock('../src/components/LeftPanel', () => ({
  default: () => <div>LeftPanel</div>,
}))

vi.mock('../src/components/RightPanel', () => ({
  default: () => <div>RightPanel</div>,
}))

vi.mock('../src/components/GraphCanvas', () => ({
  default: () => <div>GraphCanvas</div>,
}))

vi.mock('../src/components/PageWorkbench', () => ({
  default: ({ title, children }: { title: string; children: ReactNode }) => (
    <div>
      <div>{title}</div>
      <div>{children}</div>
    </div>
  ),
}))

vi.mock('../src/pages/OpsWorkbench', () => ({
  default: () => <div>Ops Workbench Page</div>,
}))

vi.mock('../src/pages/IngestPage', () => ({
  default: () => <div>Ingest Page</div>,
}))

vi.mock('../src/pages/DiscoveryPage', () => ({
  default: () => <div>Discovery Page</div>,
}))

vi.mock('../src/pages/PaperDetailPage', () => ({
  default: () => <div>Paper Detail</div>,
}))

vi.mock('../src/pages/TextbookDetailPage', () => ({
  default: () => <div>Textbook Detail</div>,
}))

import App from '../src/App'

describe('App discovery route retirement', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/discovery')
  })

  test('redirects /discovery to /ops', async () => {
    render(<App />)

    expect(await screen.findByText('Ops Workbench Page')).toBeInTheDocument()
    expect(screen.queryByText('Discovery Page')).not.toBeInTheDocument()
  })
})
