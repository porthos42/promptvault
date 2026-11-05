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
    variations: [],
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
        return json([
          { slug: 'sales', name: 'Sales', parent: null, icon: null, prompt_count: 1 },
          { slug: 'creative', name: 'Creative', parent: null, icon: null, prompt_count: 0 },
          { slug: 'design', name: 'Design', parent: 'creative', icon: null, prompt_count: 3 },
          { slug: 'music', name: 'Music', parent: 'creative', icon: null, prompt_count: 4 },
        ])
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
    expect(screen.queryByRole('button', { name: 'More actions' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'More actions' }))
    expect(screen.queryByRole('menuitem', { name: 'Reset to original' })).not.toBeInTheDocument()
    first.unmount()

    p1Modified = true
    renderAt('/p/p1')
    await user.click(await screen.findByRole('button', { name: 'More actions' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Reset to original' }))
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/prompts/p1/reset')).toBe(true),
    )
    await user.click(screen.getByRole('button', { name: 'More actions' }))
    expect(screen.queryByRole('menuitem', { name: 'Reset to original' })).not.toBeInTheDocument()
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

  it('groups categories in collapsible sections and expands the active one', async () => {
    const user = userEvent.setup()
    const first = renderAt('/')
    const toggle = await screen.findByRole('button', { name: 'Expand Creative' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: /Design/ })).not.toBeInTheDocument()
    // group count is the sum of its children (the group itself has no prompts)
    expect(screen.getByRole('link', { name: /Creative\s*7/ })).toBeInTheDocument()
    await user.click(toggle)
    expect(screen.getByRole('link', { name: /Design/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Music/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Collapse Creative' }))
    expect(screen.queryByRole('link', { name: /Design/ })).not.toBeInTheDocument()
    first.unmount()

    renderAt('/?category=design')
    const design = await screen.findByRole('link', { name: /Design/ })
    expect(design).toHaveClass('active')
    expect(screen.getByRole('button', { name: 'Collapse Creative' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('hides secondary filters behind a Filters control with a count and removable chips', async () => {
    const user = userEvent.setup()
    renderAt('/?difficulty=beginner&tags=b2b&tags=cold')
    await screen.findByRole('option', { name: /Cold email/ })
    const toggle = screen.getByRole('button', { name: /Filters/ })
    expect(toggle).toHaveAccessibleName('Filters, 3 active')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText('Difficulty')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Search prompts')).toBeInTheDocument()
    expect(screen.getByLabelText('Sort')).toBeInTheDocument()

    await user.click(toggle)
    expect(screen.getByLabelText('Difficulty')).toHaveValue('beginner')
    expect(screen.getByLabelText('Category')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove tag b2b' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Filters/ })).toHaveAccessibleName('Filters, 2 active'))
    const urls = calls.filter((c) => c.url.startsWith('/api/v1/prompts?')).map((c) => c.url)
    const lastUrl = urls[urls.length - 1]
    expect(lastUrl).toContain('tags=cold')
    expect(lastUrl).not.toContain('tags=b2b')

    await user.click(screen.getByRole('button', { name: 'Clear all' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Filters' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  })

  it('shows at most two tags plus a +N in list rows', async () => {
    renderAt('/')
    const row = await screen.findByRole('option', { name: /Cold email/ })
    expect(row).toHaveTextContent('Sales · beginner · #b2b')
  })

  it('collapses metadata under a Details toggle', async () => {
    const user = userEvent.setup()
    renderAt('/p/p1')
    await screen.findByLabelText('Name')
    const toggle = screen.getByRole('button', { name: /Details/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Shipped prompt')).not.toBeInTheDocument()
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Shipped prompt')).toBeInTheDocument()
    expect(screen.getByText('0 times')).toBeInTheDocument()
  })

  it('opens and closes the mobile navigation drawer', async () => {
    const user = userEvent.setup()
    renderAt('/')
    const burger = await screen.findByRole('button', { name: 'Open navigation' })
    expect(burger).toHaveAttribute('aria-expanded', 'false')
    await user.click(burger)
    expect(burger).toHaveAttribute('aria-expanded', 'true')
    await user.click(screen.getByRole('link', { name: /Sales/ }))
    await waitFor(() => expect(burger).toHaveAttribute('aria-expanded', 'false'))
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
