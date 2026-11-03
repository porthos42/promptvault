import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ExportPanel from './ExportPanel'
import type { ExportFormat } from '../api'

const formats: ExportFormat[] = [
  { name: 'json', extension: 'json', media_type: 'application/json', description: 'Lossless JSON export', available: true, reason: null },
  { name: 'csv', extension: 'csv', media_type: 'text/csv', description: 'Spreadsheet CSV', available: true, reason: null },
  { name: 'xlsx', extension: 'xlsx', media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', description: 'Excel workbook', available: false, reason: 'Install the xlsx extra: promptvault[xlsx]' },
]

let calls: { method: string; url: string; body?: unknown }[]

beforeEach(() => {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL, init?: RequestInit) => {
    calls.push({ method: init?.method ?? 'GET', url: String(url), body: init?.body })
    const json = (body: unknown, status = 200) => ({
      ok: status < 400,
      status,
      statusText: 'x',
      json: async () => body,
    })
    if (String(url).includes('/export/formats')) return json(formats)
    if (String(url).startsWith('/api/v1/prompts?')) return json({ items: [], total: 7, next_cursor: null, sort: 'title', corrected_query: null })
    if (init?.method === 'POST' && String(url).endsWith('/export')) return {
      ok: true,
      status: 200,
      blob: async () => new Blob(['data']),
      headers: new Headers({
        'Content-Disposition': 'attachment; filename="promptvault-export-20261103.json"',
        'X-Export-Count': '213',
        'X-Export-Warnings': '2',
      }),
    }
    return json({}, 404)
  }))
  const cu = URL as unknown as Record<string, unknown>
  cu.createObjectURL = vi.fn(() => 'blob:u')
  cu.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ExportPanel', () => {
  it('renders format cards and disables unavailable ones with the server reason', async () => {
    render(<ExportPanel filters={{}} />)
    const xlsx = await screen.findByRole('radio', { name: /XLSX/ })
    expect(xlsx).toBeDisabled()
    expect(screen.getByText('Install the xlsx extra: promptvault[xlsx]')).toBeInTheDocument()
    const json = screen.getByRole('radio', { name: /JSON/ })
    expect(json).toBeChecked()
  })

  it('shows the live count from the list endpoint total', async () => {
    render(<ExportPanel filters={{ q: 'email' }} />)
    expect(await screen.findByText('7 prompts selected')).toBeInTheDocument()
  })

  it('downloads via POST /export with the scope, filters and option defaults', async () => {
    const user = userEvent.setup()
    render(<ExportPanel filters={{ q: 'email', tags: ['b2b'] }} />)
    await user.click(await screen.findByRole('button', { name: 'Download' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('promptvault-export-20261103.json — 213 prompts — 2 warning(s)'))
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.url).toBe('/api/v1/export')
    const body = JSON.parse(String(post.body)) as Record<string, unknown>
    expect(body.format).toBe('json')
    expect(body.filters).toEqual({ q: 'email', tags: ['b2b'] })
    expect(body.include_trashed).toBe(false)
    expect(body.pretty).toBe(false)
    expect(body.bom).toBe(true)
    expect(body.raw).toBe(false)
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled()
  })

  it('switches to the whole library scope and honours the include-trash option', async () => {
    const user = userEvent.setup()
    render(<ExportPanel filters={{ q: 'email' }} />)
    await screen.findByRole('radio', { name: /JSON/ })
    await user.click(screen.getByRole('radio', { name: /Whole library/ }))
    await user.click(screen.getByRole('checkbox', { name: 'Include trash' }))
    await user.click(screen.getByRole('button', { name: 'Download' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.method === 'POST')!.body)) as Record<string, unknown>
    expect(body.filters).toEqual({})
    expect(body.include_trashed).toBe(true)
  })

  it('shows the problem+json detail when the server refuses (413 too many rows)', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/export/formats')) {
        return { ok: true, status: 200, json: async () => formats }
      }
      if (u.startsWith('/api/v1/prompts?')) return { ok: true, status: 200, json: async () => ({ items: [], total: 90000, next_cursor: null, sort: 'title', corrected_query: null }) }
      if (init?.method === 'POST' && u.endsWith('/export')) {
        return {
          ok: false,
          status: 413,
          json: async () => ({ title: 'Export too large', detail: 'This export would contain 90000 prompts; the limit is 50000.' }),
        }
      }
      return { ok: false, status: 404, json: async () => ({}) }
    }))
    render(<ExportPanel filters={{}} />)
    await user.click(await screen.findByRole('button', { name: 'Download' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('This export would contain 90000 prompts; the limit is 50000.')
  })
})

describe('filenameFromDisposition (lib/download)', () => {
  it('parses the server file name', async () => {
    const { filenameFromDisposition } = await import('../lib/download')
    expect(filenameFromDisposition('attachment; filename="promptvault-export-20261103.csv"')).toBe(
      'promptvault-export-20261103.csv',
    )
    expect(filenameFromDisposition(null)).toBeNull()
  })
})
