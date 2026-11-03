import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from 'react-router'
import { makeMemoryRouter } from '../App'
import type { ImporterInfo, ImportPreview } from '../api'

const importers: ImporterInfo[] = [
  { name: 'json', description: 'JSON list of prompts', available: true, reason: null },
  { name: 'csv', description: 'CSV with a header row', available: true, reason: null },
  { name: 'markdown', description: 'Markdown files or a ZIP', available: true, reason: null },
  { name: 'clipboard', description: 'Pasted text: one prompt, or several split by a --- / ### line (or your delimiter)', available: true, reason: null },
  { name: 'xlsx', description: 'Excel workbook', available: false, reason: 'xlsx: install the optional extra: uv pip install "prompt-vault[xlsx]"' },
]

function draft(index: number, license: string | null = null) {
  return {
    title: `Prompt ${index}`,
    body: `Body of prompt ${index}.`,
    description: '',
    category: null,
    tags: [],
    difficulty: null,
    prompt_type: null,
    model_hints: null,
    output_format: null,
    disclaimer: null,
    source_url: null,
    license,
    variables: [],
  }
}

function previewFixture(): ImportPreview {
  return {
    importer: 'csv',
    total: 3,
    new: 1,
    duplicate: 1,
    invalid: 1,
    needs_license_confirm: 1,
    rows: [
      {
        index: 0,
        status: 'new',
        errors: [],
        warnings: ['columns mapped: title<-Name, body<-Text', 'columns ignored: extra'],
        needs_license_confirm: false,
        draft: draft(0),
        match: null,
      },
      {
        index: 1,
        status: 'duplicate',
        errors: [],
        warnings: [],
        needs_license_confirm: false,
        draft: draft(1),
        match: { kind: 'fuzzy', score: 0.95, title: 'Existing prompt', prompt_id: 'abc123', batch_index: null },
      },
      {
        index: 2,
        status: 'invalid',
        errors: ['title: must not be empty', 'body: must not be empty'],
        warnings: [],
        needs_license_confirm: false,
        draft: { ...draft(2), title: '', body: '' },
        match: null,
      },
    ],
  }
}

let posts: { url: string; body: unknown }[] = []
type CommitResp = { status?: number; body: Record<string, unknown> }
let commitResponses: CommitResp[]
let preview: ImportPreview
let jobResponses: unknown[]
let jobCalls: number

beforeEach(() => {
  posts = []
  preview = previewFixture()
  commitResponses = []
  jobResponses = []
  jobCalls = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string | URL, init?: { method?: string; body?: string }) => {
      const u = String(url)
      const json = (body: unknown, status = 200) => ({
        ok: status < 400,
        status,
        statusText: 'x',
        json: async () => body,
      })
      if (init?.method === 'POST') posts.push({ url: u, body: JSON.parse(init.body ?? '{}') })
      if (u.endsWith('/import/importers')) return json(importers)
      if (u.endsWith('/import/preview')) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const maybeError = (preview as any).__status
        if (maybeError) return json({ detail: 'Request body exceeds 5242880 bytes' }, 413)
        return json(preview)
      }
      if (u.endsWith('/import/commit')) {
        const resp: CommitResp | undefined = commitResponses.shift()
        return json(resp ? resp.body : { ...inlineJob }, resp?.status ?? 200)
      }
      if (u.includes('/jobs/')) {
        jobCalls++
        const next = jobResponses[Math.min(jobCalls - 1, jobResponses.length - 1)]
        return json(next)
      }
      return json({}, 404)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const inlineJob = {
  id: 'job1',
  importer: 'csv',
  status: 'done',
  total: 3,
  processed: 3,
  created: 1,
  replaced: 1,
  skipped: 1,
  invalid: 0,
  refused: 0,
  error: null,
  created_at: '2026-11-03T00:00:00Z',
  results: [
    { index: 0, title: 'Prompt 0', outcome: 'created', prompt_id: 'new1', reason: null },
    { index: 1, title: 'Prompt 1', outcome: 'replaced', prompt_id: 'abc123', reason: null },
    { index: 2, title: 'Prompt 2', outcome: 'skipped', prompt_id: null, reason: null },
  ],
}

function pendingJob(processed: number) {
  return { ...inlineJob, status: 'pending', processed, results: null }
}

function renderWizard() {
  return render(<RouterProvider router={makeMemoryRouter('/data?tab=import')} />)
}

async function chooseCsvAndPreview(user: ReturnType<typeof userEvent.setup>, file = new File(['Name,Text\nA,B'], 'p.csv', { type: 'text/csv' })) {
  await user.click(await screen.findByRole('radio', { name: /csv/ }))
  await user.upload(screen.getByLabelText(/choose a file/i), file)
  await user.click(screen.getByRole('button', { name: /next: check the data/i }))
  await screen.findByRole('table', { name: /column mapping/i })
}

describe('ImportWizard', () => {
  it('runs the full flow: source, mapping shown, skip to preview, commit inline, result', async () => {
    const user = userEvent.setup()
    renderWizard()
    await screen.findByRole('radio', { name: /csv/ })
    await chooseCsvAndPreview(user)
    // Mapping step was derived from the preview's own warnings.
    expect(screen.getByLabelText('Column for title')).toHaveValue('Name')
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    expect(await screen.findByRole('table', { name: /import preview/i })).toBeInTheDocument()
    expect(screen.getByText(/3 rows: 1 new, 1 duplicate, 1 invalid/)).toBeInTheDocument()
    const commit = screen.getByRole('button', { name: /^Import: 1 new, 0 replaced, 1 skipped, 1 invalid skipped$/ })
    expect(commit).toBeEnabled()
    await user.click(commit)
    await screen.findByText('Import complete', {}, { timeout: 2000 })
    expect(screen.getByText(/1 created, 1 replaced, 1 skipped/)).toBeInTheDocument()
    const posted = posts.find((p) => p.url.endsWith('/import/commit'))?.body as Record<string, unknown>
    expect(posted.default_action).toBe('skip')
    expect(posted.importer).toBe('csv')
    expect(posts.every((p) => !JSON.stringify(p.body).includes('""'))).toBe(true)
  })

  it('changes the commit body when the mapping override is applied', async () => {
    const user = userEvent.setup()
    renderWizard()
    await chooseCsvAndPreview(user)
    await user.selectOptions(screen.getByLabelText('Column for title'), 'Text')
    await user.click(screen.getByRole('button', { name: /re-run preview/i }))
    await screen.findByRole('table', { name: /import preview/i })
    const previewPost = posts.filter((p) => p.url.endsWith('/import/preview')).pop()?.body as Record<string, unknown>
    expect((previewPost.source as Record<string, unknown>).mapping).toEqual({ title: 'Text', body: 'Text' })
  })

  it('blocks commit until licenses are confirmed and sends confirm_license', async () => {
    const user = userEvent.setup()
    preview = {
      ...previewFixture(),
      rows: previewFixture().rows.map((r, i) => (i === 0 ? { ...r, needs_license_confirm: true } : r)),
      needs_license_confirm: 1,
    }
    renderWizard()
    await chooseCsvAndPreview(user)
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    const commit = await screen.findByRole('button', { name: /^Import: 1 new, 0 replaced, 1 skipped, 1 invalid skipped$/ })
    expect(commit).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /confirm all/i }))
    expect(commit).toBeEnabled()
    await user.click(commit)
    await screen.findByText('Import complete')
    const posted = posts.find((p) => p.url.endsWith('/import/commit'))?.body as Record<string, unknown>
    expect(posted.confirm_license).toBe(true)
  })

  it('per-row duplicate override changes the commit body actions', async () => {
    const user = userEvent.setup()
    renderWizard()
    await chooseCsvAndPreview(user)
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await screen.findByText('Prompt 1', {}, { timeout: 2000 })
    const table = screen.getByRole('table', { name: /import preview/i })
    const dupRow = within(table).getByText('Prompt 1').closest('tr') as HTMLElement
    await user.click(within(dupRow).getByRole('button', { name: 'Show' }))
    await user.selectOptions(screen.getByLabelText('Action for row 2'), 'replace')
    await user.click(screen.getByRole('button', { name: /^Import: 1 new, 1 replaced, 0 skipped/ }))
    await screen.findByText('Import complete')
    const posted = posts.find((p) => p.url.endsWith('/import/commit'))?.body as Record<string, unknown>
    expect(posted.actions).toEqual({ '1': 'replace' })
  })

  it('shows unavailable importers disabled with their reason', async () => {
    renderWizard()
    const radio = await screen.findByRole('radio', { name: /xlsx/ })
    expect(radio).toBeDisabled()
    expect(screen.getByText(/install the optional extra/i)).toBeInTheDocument()
  })

  it('surfaces a 413 problem+json detail as an alert', async () => {
    const user = userEvent.setup()
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(preview as any).__status = 413
    renderWizard()
    await screen.findByRole('radio', { name: /csv/ })
    await user.click(screen.getByRole('radio', { name: /csv/ }))
    await user.upload(screen.getByLabelText(/choose a file/i), new File(['x'], 'p.csv', { type: 'text/csv' }))
    await user.click(screen.getByRole('button', { name: /next: check the data/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/body exceeds/i)
  })

  it('polls a 202 job every 500ms to done with a progress bar', async () => {
    const user = userEvent.setup()
    commitResponses.push({ status: 202, body: pendingJob(1) })
    jobResponses.push(pendingJob(2), { ...inlineJob, status: 'running', processed: 3 }, { ...inlineJob })
    renderWizard()
    await chooseCsvAndPreview(user)
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(await screen.findByRole('button', { name: /^Import: 1 new, 0 replaced, 1 skipped/ }))
    // First poll shows a progress bar; later polls land on the result.
    await screen.findByRole('progressbar')
    await screen.findByText('Import complete', {}, { timeout: 4000 })
    expect(jobCalls).toBeGreaterThanOrEqual(2)
  })

  it('keeps the preview and shows the error when a job fails', async () => {
    const user = userEvent.setup()
    commitResponses.push({ status: 202, body: pendingJob(0) })
    jobResponses.push({ ...inlineJob, status: 'failed', error: 'The database is locked', results: null })
    renderWizard()
    await chooseCsvAndPreview(user)
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(await screen.findByRole('button', { name: /^Import: 1 new, 0 replaced, 1 skipped/ }))
    expect(await screen.findByRole('alert', {}, { timeout: 3000 })).toHaveTextContent('The database is locked')
    expect(screen.getByRole('table', { name: /import preview/i })).toBeInTheDocument()
  })

  it('shows an empty state when the source parses to zero rows', async () => {
    const user = userEvent.setup()
    preview = { ...previewFixture(), total: 0, new: 0, duplicate: 0, invalid: 0, rows: [] }
    renderWizard()
    await screen.findByRole('radio', { name: /csv/ })
    await user.click(screen.getByRole('radio', { name: /csv/ }))
    await user.upload(screen.getByLabelText(/choose a file/i), new File(['Name,Text'], 'p.csv', { type: 'text/csv' }))
    await user.click(screen.getByRole('button', { name: /next: check the data/i }))
    // No mapping notes -> straight to the preview step with the empty state.
    expect(await screen.findByText(/parsed to zero prompts/i)).toBeInTheDocument()
  })

  it('does not send empty default_license or default_source_url strings', async () => {
    const user = userEvent.setup()
    renderWizard()
    await screen.findByRole('radio', { name: /csv/ })
    await user.click(screen.getByRole('radio', { name: /csv/ }))
    await user.type(screen.getByLabelText(/^license/i), ' ')
    await user.upload(screen.getByLabelText(/choose a file/i), new File(['Name,Text\nA,B'], 'p.csv', { type: 'text/csv' }))
    await user.click(screen.getByRole('button', { name: /next: check the data/i }))
    await screen.findByRole('table', { name: /column mapping/i })
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(await screen.findByRole('button', { name: /^Import: 1 new, 0 replaced, 1 skipped/ }))
    await screen.findByText('Import complete')
    const posted = posts.find((p) => p.url.endsWith('/import/commit'))?.body as Record<string, unknown>
    expect(posted.default_license).toBeUndefined()
    expect(posted.default_source_url).toBeUndefined()
  })
})

describe('ImportWizard step persistence and reset', () => {
  it('keeps the step in the URL and returns to the source on Start over', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderWizard()
    await chooseCsvAndPreview(user)
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await screen.findByRole('table', { name: /import preview/i })
    expect(screen.getByText('3. Preview').closest('li')).toHaveAttribute('aria-current', 'step')
    await user.click(screen.getByRole('button', { name: 'Start over' }))
    expect(await screen.findByRole('radio', { name: /csv/ })).toBeInTheDocument()
    expect(screen.getByText('1. Source').closest('li')).toHaveAttribute('aria-current', 'step')
    confirm.mockRestore()
  })

  it('warns before navigating away with a preview loaded', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    renderWizard()
    await chooseCsvAndPreview(user)
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await screen.findByRole('table', { name: /import preview/i })
    await user.click(screen.getByRole('link', { name: 'All prompts' }))
    await waitFor(() => expect(confirm).toHaveBeenCalled())
    expect(screen.getByRole('table', { name: /import preview/i })).toBeInTheDocument()
    confirm.mockRestore()
  })
})

describe('ImportWizard clipboard source', () => {
  it('uses the paste box and delimiter for the clipboard importer', async () => {
    const user = userEvent.setup()
    renderWizard()
    await user.click(await screen.findByRole('radio', { name: /clipboard/ }))
    await user.type(screen.getByLabelText(/paste your prompts/i), '# Title\nBody')
    await user.type(screen.getByLabelText('Delimiter (optional)'), '###')
    await user.click(screen.getByRole('button', { name: /next: check the data/i }))
    await waitFor(() => expect(posts.some((p) => p.url.endsWith('/import/preview'))).toBe(true))
    const posted = posts.find((p) => p.url.endsWith('/import/preview'))?.body as { source: Record<string, unknown> }
    expect(posted.source).toEqual({ content: '# Title\nBody', delimiter: '###' })
  })
})
