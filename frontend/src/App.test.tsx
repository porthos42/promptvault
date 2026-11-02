import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeMemoryRouter } from './App'
import type { Prompt } from './api'

function prompt(over: Partial<Prompt> = {}): Prompt {
  return {
    id: 'p1',
    seed_id: 'cold-email',
    seed_modified: false,
    title: 'Cold email',
    body: 'Write to {{name}} about {{topic}}.',
    description: 'Outreach helper',
    category: { slug: 'sales', name: 'Sales' },
    tags: ['b2b'],
    variables: [
      { name: 'name', label: 'Name', type: 'text', default: '', options: [] },
      { name: 'topic', label: 'Topic', type: 'text', default: 'pricing', options: [] },
    ],
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
    ...over,
  }
}

let calls: { method: string; url: string }[]
let trashed: Prompt[]
let p1Modified: boolean

beforeEach(() => {
  calls = []
  p1Modified = false
  trashed = [prompt({ id: 't1', title: 'Old draft', deleted_at: '2026-01-02T00:00:00Z' })]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ method, url })
      const json = (body: unknown, status = 200) => ({
        ok: status < 400,
        status,
        statusText: 'x',
        json: async () => body,
      })
      if (url.startsWith('/api/v1/categories'))
        return json([{ slug: 'sales', name: 'Sales', parent: null, icon: null, prompt_count: 1 }])
      if (url.includes('/use')) return json(prompt({ use_count: 1 }))
      if (url.match(/\/prompts\/t1\/restore/)) return json(prompt({ id: 't1' }))
      if (url.match(/\/prompts\/p1\/reset/)) {
        p1Modified = false
        return json(prompt())
      }
      if (url.match(/\/prompts\/p1$/)) return json(prompt({ seed_modified: p1Modified }))
      if (url.startsWith('/api/v1/prompts')) {
        const items = url.includes('trash=true') ? trashed : [prompt({ seed_modified: p1Modified })]
        return json({ items, total: items.length, next_cursor: null, sort: 'relevance', corrected_query: null })
      }
      return json({}, 404)
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderAt(path: string) {
  return render(<RouterProvider router={makeMemoryRouter(path)} />)
}

describe('Library UI', () => {
  it('lists prompts and categories and passes URL filters to the API', async () => {
    renderAt('/?q=email&difficulty=beginner&tags=b2b')
    expect(await screen.findByRole('option', { name: /Cold email/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Sales/ })).toBeInTheDocument()
    const listCall = calls.find((c) => c.url.startsWith('/api/v1/prompts?'))!
    expect(listCall.url).toContain('q=email')
    expect(listCall.url).toContain('difficulty=beginner')
    expect(listCall.url).toContain('tags=b2b')
    expect(screen.getByLabelText('Search prompts')).toHaveValue('email')
  })

  it('fills variables, live-previews, and copies the rendered text', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderAt('/p/p1')
    const name = await screen.findByLabelText('Name')
    expect(screen.getByTestId('preview')).toHaveTextContent('Write to {{name}} about pricing.')
    await user.type(name, 'Ada')
    expect(screen.getByTestId('preview')).toHaveTextContent('Write to Ada about pricing.')
    await user.click(screen.getByRole('button', { name: 'Copy' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('Write to Ada about pricing.'))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/p1/use'))).toBe(true))
  })

  it('offers Reset to original only for edited seed prompts', async () => {
    const user = userEvent.setup()
    const first = renderAt('/p/p1')
    await screen.findByLabelText('Name')
    expect(screen.queryByRole('button', { name: 'Reset to original' })).not.toBeInTheDocument()
    first.unmount()

    p1Modified = true
    renderAt('/p/p1')
    await user.click(await screen.findByRole('button', { name: 'Reset to original' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/prompts/p1/reset')).toBe(true),
    )
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Reset to original' })).not.toBeInTheDocument())
  })

  it('opens the command palette with Ctrl+K and searches', async () => {
    const user = userEvent.setup()
    renderAt('/')
    await screen.findByRole('option', { name: /Cold email/ })
    await user.keyboard('{Control>}k{/Control}')
    const dialog = await screen.findByRole('dialog', { name: 'Command palette' })
    expect(dialog).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})

describe('Trash', () => {
  it('lists trashed prompts and restores one', async () => {
    const user = userEvent.setup()
    renderAt('/trash')
    expect(await screen.findByText('Old draft')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Restore' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/prompts/t1/restore')).toBe(true),
    )
  })
})
