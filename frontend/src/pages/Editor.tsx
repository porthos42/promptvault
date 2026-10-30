import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext, useParams } from 'react-router'
import { api, type Difficulty } from '../api'
import CodeEditor from '../components/CodeEditor'
import type { ShellContext } from '../Shell'

type Draft = {
  title: string
  body: string
  description: string
  category: string
  tags: string
  difficulty: Difficulty
  output_format: string
  model_hints: string
  disclaimer: string
}

const EMPTY: Draft = {
  title: '',
  body: '',
  description: '',
  category: '',
  tags: '',
  difficulty: 'beginner',
  output_format: '',
  model_hints: '',
  disclaimer: '',
}

export default function Editor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { categories, bump } = useOutletContext<ShellContext>()
  const [draft, setDraft] = useState<Draft | null>(id ? null : EMPTY)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!id) return
    let live = true
    api
      .getPrompt(id)
      .then((p) => {
        if (!live) return
        setDraft({
          title: p.title,
          body: p.body,
          description: p.description,
          category: p.category?.slug ?? '',
          tags: p.tags.join(', '),
          difficulty: p.difficulty,
          output_format: p.output_format ?? '',
          model_hints: p.model_hints ?? '',
          disclaimer: p.disclaimer ?? '',
        })
      })
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [id])

  if (!draft) return error ? <p role="alert" className="error">{error}</p> : <p className="empty">Loading...</p>

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d))

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    const payload = {
      title: draft.title.trim(),
      body: draft.body,
      description: draft.description,
      category: draft.category || null,
      tags: draft.tags
        .split(',')
        .map((t) => t.trim().toLowerCase())
        .filter(Boolean),
      difficulty: draft.difficulty,
      output_format: draft.output_format || null,
      model_hints: draft.model_hints || null,
      disclaimer: draft.disclaimer || null,
    }
    try {
      const saved = id ? await api.patchPrompt(id, payload) : await api.createPrompt(payload)
      bump()
      navigate(`/p/${saved.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setSaving(false)
    }
  }

  return (
    <form className="editor" onSubmit={save}>
      <h2>{id ? 'Edit prompt' : 'New prompt'}</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="field">
        <label htmlFor="f-title">Title</label>
        <input id="f-title" required maxLength={300} value={draft.title} onChange={(e) => set('title', e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="f-desc">Description</label>
        <input id="f-desc" value={draft.description} onChange={(e) => set('description', e.target.value)} />
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor="f-cat">Category</label>
          <select id="f-cat" value={draft.category} onChange={(e) => set('category', e.target.value)}>
            <option value="">None</option>
            {categories.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-diff">Difficulty</label>
          <select
            id="f-diff"
            value={draft.difficulty}
            onChange={(e) => set('difficulty', e.target.value as Difficulty)}
          >
            <option value="beginner">Beginner</option>
            <option value="intermediate">Intermediate</option>
            <option value="advanced">Advanced</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-tags">Tags (comma separated)</label>
          <input id="f-tags" value={draft.tags} onChange={(e) => set('tags', e.target.value)} />
        </div>
      </div>
      <div className="field">
        <span className="label">
          Body <span className="dim">use {'{{variable}}'} for placeholders</span>
        </span>
        <CodeEditor label="Prompt body" value={draft.body} onChange={(v) => set('body', v)} />
      </div>
      <div className="field-row">
        <div className="field">
          <label htmlFor="f-model">Model hints</label>
          <input id="f-model" value={draft.model_hints} onChange={(e) => set('model_hints', e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="f-out">Output format</label>
          <input id="f-out" value={draft.output_format} onChange={(e) => set('output_format', e.target.value)} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="f-disc">Disclaimer</label>
        <input id="f-disc" value={draft.disclaimer} onChange={(e) => set('disclaimer', e.target.value)} />
      </div>
      <div className="toolbar">
        <button className="primary" type="submit" disabled={saving || !draft.title.trim() || !draft.body.trim()}>
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button type="button" onClick={() => navigate(id ? `/p/${id}` : '/')}>
          Cancel
        </button>
      </div>
    </form>
  )
}
