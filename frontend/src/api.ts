export type Health = { status: string }
export type Version = { version: string }

export type Difficulty = 'beginner' | 'intermediate' | 'advanced'
export type VariableType = 'text' | 'textarea' | 'number' | 'select'
export type Variable = {
  name: string
  label: string
  type: VariableType
  default: string
  options: string[]
}
export type Prompt = {
  id: string
  seed_id: string | null
  seed_modified: boolean
  title: string
  body: string
  description: string
  category: { slug: string; name: string } | null
  tags: string[]
  variables: Variable[]
  model_hints: string | null
  output_format: string | null
  difficulty: Difficulty
  prompt_type: string
  disclaimer: string | null
  source: string
  is_favorite: boolean
  use_count: number
  updated_at: string
  deleted_at: string | null
}
export type PromptList = {
  items: Prompt[]
  total: number
  next_cursor: string | null
  sort: string
  corrected_query: string | null
}
export type Category = {
  slug: string
  name: string
  parent: string | null
  icon: string | null
  prompt_count: number
}
export type Tag = { name: string; prompt_count: number }
export type PromptInput = Partial<
  Pick<
    Prompt,
    'title' | 'body' | 'description' | 'tags' | 'difficulty' | 'model_hints' | 'output_format' | 'disclaimer'
  >
> & { category?: string | null; is_favorite?: boolean }

export type ListQuery = Record<string, string | string[] | undefined>

export type ExportFormat = {
  name: string
  extension: string
  media_type: string
  description: string
  available: boolean
  reason: string | null
}
export type ShareOut = { format: 'markdown' | 'text' | 'json'; text: string; missing: string[] }
export type ExportOptions = { pretty: boolean; bom: boolean; raw: boolean }
export type Download = { blob: Blob; headers: Headers }

// ---- import (docs/SPEC.md 3.5) --------------------------------------------------------------

export type ImporterInfo = { name: string; description: string; available: boolean; reason: string | null }
export type ImportDraft = {
  title: string
  body: string
  description: string
  category: string | null
  tags: string[]
  difficulty: string | null
  prompt_type: string | null
  model_hints: string | null
  output_format: string | null
  disclaimer: string | null
  source_url: string | null
  license: string | null
  variables: string[]
}
export type ImportMatch = {
  kind: 'exact' | 'fuzzy'
  score: number
  title: string
  prompt_id: string | null
  batch_index: number | null
}
export type PreviewRow = {
  index: number
  status: 'new' | 'duplicate' | 'invalid'
  errors: string[]
  warnings: string[]
  needs_license_confirm: boolean
  draft: ImportDraft
  match: ImportMatch | null
}
export type ImportPreview = {
  importer: string
  total: number
  new: number
  duplicate: number
  invalid: number
  needs_license_confirm: number
  rows: PreviewRow[]
}
export type DupAction = 'skip' | 'replace' | 'keep_both'
export type PreviewRequest = { importer: string; source: unknown; default_license?: string; default_source_url?: string }
export type CommitRequest = PreviewRequest & {
  default_action: DupAction
  actions: Record<string, DupAction>
  confirm_license: boolean
  confirmed_rows: number[]
}
export type ImportOutcome = 'created' | 'replaced' | 'skipped' | 'invalid' | 'refused'
export type JobResult = { index: number; title: string; outcome: ImportOutcome; prompt_id: string | null; reason: string | null }
export type ImportJob = {
  id: string
  importer: string
  status: 'pending' | 'running' | 'done' | 'failed'
  total: number
  processed: number
  created: number
  replaced: number
  skipped: number
  invalid: number
  refused: number
  error: string | null
  created_at: string
  results: JobResult[] | null
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const p = (await res.json()) as { detail?: unknown; title?: string }
      if (typeof p.detail === 'string') detail = p.detail
      else if (p.title) detail = p.title
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export function toQueryString(q: ListQuery): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === '') continue
    for (const item of Array.isArray(v) ? v : [v]) sp.append(k, item)
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  health: () => request<Health>('GET', '/health'),
  version: () => request<Version>('GET', '/version'),
  listPrompts: (q: ListQuery) => request<PromptList>('GET', `/prompts${toQueryString(q)}`),
  getPrompt: (id: string) => request<Prompt>('GET', `/prompts/${id}`),
  createPrompt: (b: PromptInput) => request<Prompt>('POST', '/prompts', b),
  patchPrompt: (id: string, b: PromptInput) => request<Prompt>('PATCH', `/prompts/${id}`, b),
  deletePrompt: (id: string, permanent = false) =>
    request<void>('DELETE', `/prompts/${id}${permanent ? '?permanent=true' : ''}`),
  restorePrompt: (id: string) => request<Prompt>('POST', `/prompts/${id}/restore`),
  resetPrompt: (id: string) => request<Prompt>('POST', `/prompts/${id}/reset`),
  duplicatePrompt: (id: string) => request<Prompt>('POST', `/prompts/${id}/duplicate`),
  markUsed: (id: string) => request<Prompt>('POST', `/prompts/${id}/use`),
  emptyTrash: () => request<{ purged: number }>('DELETE', '/trash'),
  categories: () => request<Category[]>('GET', '/categories'),
  tags: () => request<Tag[]>('GET', '/tags'),
  exportFormats: () => request<ExportFormat[]>('GET', '/export/formats'),
  /** Download an export as a Blob, with the X-Export-* headers the server reports. */
  exportDownload: async (body: {
    format: string
    ids?: string[]
    filters: Record<string, unknown>
    include_trashed: boolean
    pretty?: boolean
    bom?: boolean
    raw?: boolean
  }): Promise<Download> => {
    const res = await fetch('/api/v1/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return finishDownload(res)
  },
  exportPrompt: async (id: string, format: string, options: ExportOptions): Promise<Download> => {
    const qs = toQueryString({
      format,
      pretty: options.pretty ? 'true' : undefined,
      bom: options.bom ? undefined : 'false',
      raw: options.raw ? 'true' : undefined,
    })
    const res = await fetch(`/api/v1/prompts/${id}/export${qs}`)
    return finishDownload(res)
  },
  sharePrompt: (id: string, format: string, values: string[]) =>
    request<ShareOut>('GET', `/prompts/${id}/share${toQueryString({ format, values })}`),
  importers: () => request<ImporterInfo[]>('GET', '/import/importers'),
  importPreview: (b: PreviewRequest) => request<ImportPreview>('POST', '/import/preview', b),
  importCommit: (b: CommitRequest) => request<ImportJob>('POST', '/import/commit', b),
  job: (id: string) => request<ImportJob>('GET', `/jobs/${id}`),
}

/** Turn a fetch Response into a Blob download, reading the error body on failure. */
async function finishDownload(res: Response): Promise<Download> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const p = (await res.json()) as { detail?: unknown; title?: string }
      if (typeof p.detail === 'string') detail = p.detail
      else if (p.title) detail = p.title
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  return { blob: await res.blob(), headers: res.headers }
}
