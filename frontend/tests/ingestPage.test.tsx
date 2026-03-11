import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, test, vi } from 'vitest'

vi.mock('../src/pages/ImportedSourceManagement', () => ({
  default: () => <div>Imported Source Management</div>,
}))

import IngestPage from '../src/pages/IngestPage'

describe('IngestPage', () => {
  test('keeps upload controls visible after mounting imported source management', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/ingest']}>
        <Routes>
          <Route path="/ingest" element={<IngestPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(container.querySelector('input[name="ingest_zip_file"]')).toBeTruthy()
    expect(container.querySelector('input[name="ingest_folder_files"]')).toBeTruthy()
    expect(screen.getByText('Imported Source Management')).toBeInTheDocument()
  })
})
