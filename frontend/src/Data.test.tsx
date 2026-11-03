import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from 'react-router'
import { makeMemoryRouter } from './App'
import type { ExportFormat, Prompt } from './api'

const formats: ExportFormat[] = [
  { name: 'json', extension: 'json', media_type: 'application/json', description: 'Lossless JSON export', available: true, reason: null },
]

let calls: string[]

function prompt(): Prompt {
  return {
    id: 'p1',
    seed_id: 'cold-email',
    seed_modified: false,
    title: 'Cold email',
    body: 'Write to {{name}}.',
    description: '',
    category: { slug: 'sales', name: 'Sales' },
    tags: [],
    variables: [],
    model_hints: null,
    output_format: null,
    difficulty: 'beginner',
    prompt_type: 'template',
    disclaimer: null,
    source: 'seed',
    is_favorite: false,
    use_count: 0,
    updated_at: '2026-01-01T00:00:00Z',
    deleted_at: null,
  }
}

beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string | URL) => {
      const u = String(url)
      calls.push(u)
      const json = (body: unknown) => ({ ok: true, status: 200, statusText: 'x', json: async () => body })
      if (u.includes('/export/formats')) return json(formats)
      if (u === '/api/v1/categories')
        return json([{ slug: 'sales', name: 'Sales', parent: null, icon: null, prompt_count: 1 }])
      if (u.startsWith('/api/v1/prompts?'))
        return json({ items: [prompt()], total: 1, next_cursor: null, sort: 'recent', corrected_query: null })
      return { ok: false, status: 404, statusText: 'x', json: async () => ({}) }
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderAt(path: string) {
  return render(<RouterProvider router={makeMemoryRouter(path)} />)
}

describe('Data page', () => {
  it('lazy-loads /data with the Export tab, tabs switch to the Import placeholder', async () => {
    const user = userEvent.setup()
    renderAt('/data')
    const tablist = await screen.findByRole('tablist', { name: 'Data' })
    expect(tablist).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Export' })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByRole('radio', { name: /JSON/ })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Import' }))
    expect(screen.getByRole('tab', { name: 'Import' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText(/Import lands with the next release/)).toBeInTheDocument()
  })

  it('carries library filters from the URL into the export scope count', async () => {
    renderAt('/data?tab=export&q=email&tags=b2b')
    expect(await screen.findByText('1 prompt selected')).toBeInTheDocument()
    expect(calls.some((c) => c.includes('q=email') && c.includes('tags=b2b'))).toBe(true)
  })

  it('exposes Data in the sidebar navigation', async () => {
    const user = userEvent.setup()
    renderAt('/')
    const link = await screen.findByRole('link', { name: 'Data' })
    await user.click(link)
    expect(await screen.findByRole('tablist', { name: 'Data' })).toBeInTheDocument()
  })

  it('offers Export library and Share prompt in the command palette', async () => {
    const user = userEvent.setup()
    const view = renderAt('/')
    await screen.findByRole('option', { name: /Cold email/ })
    await user.keyboard('{Control>}k{/Control}')
    const exportCmd = await screen.findByRole('button', { name: /Export library/ })
    expect(screen.getByRole('button', { name: /Share prompt/ })).toBeDisabled()
    await user.click(exportCmd)
    expect(await screen.findByRole('tablist', { name: 'Data' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Export' })).toHaveAttribute('aria-selected', 'true')
    view.unmount()
  })
})
