import { useState } from 'react'
import { api, type Prompt } from '../api'
import { renderTemplate } from '../lib/template'

type Props = {
  prompt: Prompt
  onChanged: (p?: Prompt) => void
  onTag: (tag: string) => void
  onEdit: () => void
  onDuplicated: (p: Prompt) => void
  onDeleted: () => void
}

export default function PromptDetail({ prompt, onChanged, onTag, onEdit, onDuplicated, onDeleted }: Props) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { text, missing } = renderTemplate(prompt.body, prompt.variables, values)

  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const copy = () =>
    run(async () => {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
      const updated = await api.markUsed(prompt.id)
      onChanged(updated)
    })

  return (
    <article className="detail">
      <header>
        <h2>{prompt.title}</h2>
        <div className="toolbar">
          <button
            aria-pressed={prompt.is_favorite}
            onClick={() =>
              run(async () => onChanged(await api.patchPrompt(prompt.id, { is_favorite: !prompt.is_favorite })))
            }
          >
            {prompt.is_favorite ? '★ Favorited' : '☆ Favorite'}
          </button>
          <button onClick={onEdit}>Edit</button>
          <button onClick={() => run(async () => onDuplicated(await api.duplicatePrompt(prompt.id)))}>
            Duplicate
          </button>
          <button
            onClick={() =>
              run(async () => {
                await api.deletePrompt(prompt.id)
                onDeleted()
              })
            }
          >
            Delete
          </button>
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {prompt.description && <p>{prompt.description}</p>}
      {prompt.disclaimer && (
        <p className="disclaimer" role="note">
          {prompt.disclaimer}
        </p>
      )}
      <p className="meta">
        {prompt.category && <span className="chip">{prompt.category.name}</span>}
        <span className="chip dim">{prompt.difficulty}</span>
        {prompt.model_hints && <span className="chip dim">{prompt.model_hints}</span>}
        {prompt.tags.map((t) => (
          <button key={t} className="chip dim" onClick={() => onTag(t)}>
            #{t}
          </button>
        ))}
        <span className="dim">Used {prompt.use_count}×</span>
      </p>

      {prompt.variables.length > 0 && (
        <form className="varform" onSubmit={(e) => e.preventDefault()} aria-label="Variables">
          <h3>Variables</h3>
          {prompt.variables.map((v) => {
            const id = `var-${v.name}`
            const common = {
              id,
              value: values[v.name] ?? '',
              placeholder: v.default || undefined,
              onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
                setValues((s) => ({ ...s, [v.name]: e.target.value })),
            }
            return (
              <div key={v.name} className="field">
                <label htmlFor={id}>{v.label}</label>
                {v.type === 'textarea' ? (
                  <textarea rows={3} {...common} />
                ) : v.type === 'select' ? (
                  <select {...common}>
                    <option value="">{v.default ? `Default (${v.default})` : 'Choose...'}</option>
                    {v.options.map((o) => (
                      <option key={o}>{o}</option>
                    ))}
                  </select>
                ) : (
                  <input type={v.type === 'number' ? 'number' : 'text'} {...common} />
                )}
              </div>
            )
          })}
        </form>
      )}

      <section aria-label="Preview">
        <div className="preview-head">
          <h3>Preview</h3>
          {missing.length > 0 && <span className="dim">Missing: {missing.join(', ')}</span>}
          <button className="primary" onClick={copy}>
            {copied ? 'Copied ✓' : 'Copy'}
          </button>
        </div>
        <pre className="preview" data-testid="preview">
          {text}
        </pre>
      </section>
    </article>
  )
}
