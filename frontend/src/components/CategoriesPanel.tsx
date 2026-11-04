import { useState } from 'react'
import { api, type Category, type CategoryInput } from '../api'

type Props = {
  categories: Category[]
  bump: () => void
}

/** CRUD for categories: add, rename, move under a parent, and delete
 *  (deleting keeps prompts; they become uncategorised). */
export default function CategoriesPanel({ categories, bump }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<CategoryInput>({ name: '', parent: null })
  const [edits, setEdits] = useState<Record<string, string>>({})

  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    setBusy(true)
    try {
      await fn()
      bump()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const add = (e: React.FormEvent) => {
    e.preventDefault()
    const name = draft.name.trim()
    if (!name) return
    void run(async () => {
      await api.createCategory({ ...draft, name })
      setDraft({ name: '', parent: null })
    })
  }

  const rename = (c: Category) => {
    const name = edits[c.slug]?.trim()
    if (!name || name === c.name) return
    void run(async () => {
      await api.patchCategory(c.slug, { name })
      setEdits((s) => ({ ...s, [c.slug]: '' }))
    })
  }

  const reparent = (c: Category, parent: string | null) => {
    if (parent === c.parent) return
    void run(() => api.patchCategory(c.slug, { parent }))
  }

  const remove = (c: Category) => {
    if (c.prompt_count > 0 && !confirm(`Delete category "${c.name}"? ${c.prompt_count} prompt(s) will become uncategorised.`)) return
    void run(() => api.deleteCategory(c.slug))
  }

  return (
    <div className="cats-manage">
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <form onSubmit={add} className="field-row">
        <div className="field">
          <label htmlFor="cat-name">New category</label>
          <input
            id="cat-name"
            required
            maxLength={200}
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
        </div>
        <div className="field">
          <label htmlFor="cat-parent">Parent (optional)</label>
          <select
            id="cat-parent"
            value={draft.parent ?? ''}
            onChange={(e) => setDraft((d) => ({ ...d, parent: e.target.value || null }))}
          >
            <option value="">None (top level)</option>
            {categories.filter((c) => !c.parent).map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label aria-hidden="true">&nbsp;</label>
          <button className="primary" type="submit" disabled={busy}>
            Add category
          </button>
        </div>
      </form>
      <table className="cats-table">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Parent</th>
            <th scope="col">Prompts</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {categories.map((c) => (
            <tr key={c.slug}>
              <td>
                <input
                  aria-label={`Name of ${c.name}`}
                  value={edits[c.slug] ?? c.name}
                  onChange={(e) => setEdits((s) => ({ ...s, [c.slug]: e.target.value }))}
                  onBlur={() => rename(c)}
                  onKeyDown={(e) => e.key === 'Enter' && rename(c)}
                />
              </td>
              <td>
                <select
                  aria-label={`Parent of ${c.name}`}
                  value={c.parent ?? ''}
                  disabled={!!c.parent}
                  onChange={(e) => reparent(c, e.target.value || null)}
                >
                  <option value="">None (top level)</option>
                  {categories.filter((p) => !p.parent && p.slug !== c.slug).map((p) => (
                    <option key={p.slug} value={p.slug}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </td>
              <td>{c.prompt_count}</td>
              <td>
                <button className="quiet danger" disabled={busy} onClick={() => remove(c)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
