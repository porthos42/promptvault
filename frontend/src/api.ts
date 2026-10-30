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
  duplicatePrompt: (id: string) => request<Prompt>('POST', `/prompts/${id}/duplicate`),
  markUsed: (id: string) => request<Prompt>('POST', `/prompts/${id}/use`),
  emptyTrash: () => request<{ purged: number }>('DELETE', '/trash'),
  categories: () => request<Category[]>('GET', '/categories'),
  tags: () => request<Tag[]>('GET', '/tags'),
}
