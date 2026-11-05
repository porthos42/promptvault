import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SharePopover from './SharePopover'
import type { Prompt } from '../api'

function prompt(): Prompt {
  return {
    id: 'p1',
    seed_id: 'cold-email',
    seed_modified: false,
    title: 'Cold email',
    body: 'Write to {{name}} about {{topic}}.',
    description: '',
    category: null,
    tags: [],
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
  }
}

let calls: { url: string }[]
let onDismiss: () => void

beforeEach(() => {
  calls = []
  onDismiss = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string | URL) => {
      calls.push({ url: String(url) })
      return {
        ok: true,
        status: 200,
        json: async () =>
          String(url).includes('format=json')
            ? { format: 'json', text: '[{"role": "user", "content": "Write to Ada about pricing."}]', missing: [] }
            : { format: 'markdown', text: 'Write to Ada about pricing.', missing: ['greeting'] },
      }
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('SharePopover', () => {
  it('loads the snippet with the current variable values and shows the missing hint', async () => {
    render(<SharePopover prompt={prompt()} values={{ name: 'Ada' }} onClose={onDismiss} />)
    expect(await screen.findByTestId('share-preview')).toHaveTextContent('Write to Ada about pricing.')
    const call = calls.find((c) => c.url.includes('/share'))!
    expect(call.url).toContain('format=markdown')
    expect(call.url).toContain('values=name%3DAda')
    // unset variables are not sent, defaults are not baked in
    expect(call.url).not.toContain('topic')
    expect(screen.getByRole('dialog', { name: 'Share prompt' })).toHaveTextContent('Missing: greeting')
  })

  it('switches format to JSON on the radio group', async () => {
    const user = userEvent.setup()
    render(<SharePopover prompt={prompt()} values={{ name: 'Ada' }} onClose={onDismiss} />)
    await screen.findByTestId('share-preview')
    await user.click(screen.getByRole('radio', { name: 'JSON' }))
    await waitFor(() => expect(screen.getByTestId('share-preview')).toHaveTextContent('"role"'))
    expect(calls.some((c) => c.url.includes('format=json'))).toBe(true)
  })

  it('copies the snippet to the clipboard', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<SharePopover prompt={prompt()} values={{ name: 'Ada' }} onClose={onDismiss} />)
    await user.click(await screen.findByRole('button', { name: 'Copy snippet' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('Write to Ada about pricing.'))
    expect(screen.getByRole('button', { name: 'Copied ✓' })).toBeInTheDocument()
  })

  it('closes on Escape and returns focus to the Share button', async () => {
    const user = userEvent.setup()
    const { unmount } = render(
      <div className="toolbar">
        <button aria-label="Share" aria-haspopup="dialog" onClick={() => undefined}>
          ⤴
        </button>
        <SharePopover prompt={prompt()} values={{}} onClose={onDismiss} />
      </div>,
    )
    await screen.findByRole('dialog', { name: 'Share prompt' })
    await user.keyboard('{Escape}')
    expect(onDismiss).toHaveBeenCalled()
    await waitFor(() =>
      expect(document.activeElement?.getAttribute('aria-label')).toBe('Share'),
    )
    unmount()
  })
})
