import { useEffect, useRef, useState } from 'react'
import { api, type Prompt } from '../api'
import { renderTemplate } from '../lib/template'
import SharePopover from './SharePopover'
import { saveBlob } from '../lib/download'

type Props = {
  prompt: Prompt
  onChanged: (p?: Prompt) => void
  onTag: (tag: string) => void
  onEdit: () => void
  onDuplicated: (p: Prompt) => void
  onDeleted: () => void
  onBack?: () => void
}

export default function PromptDetail({ prompt, onChanged, onTag, onEdit, onDuplicated, onDeleted, onBack }: Props) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [menu, setMenu] = useState(false)
  const [details, setDetails] = useState(false)
  const [share, setShare] = useState(false)
  const [exportMenu, setExportMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const shareRef = useRef<HTMLDivElement>(null)
  const exportRef = useRef<HTMLDivElement>(null)

  const { text, missing } = renderTemplate(prompt.body, prompt.variables, values)

  useEffect(() => {
    if (!menu) return
    menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenu(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [menu])

  // Ctrl+K palette "Share prompt": open the share popover for this prompt.
  useEffect(() => {
    const onShare = () => setShare(true)
    window.addEventListener('pv:share', onShare)
    return () => window.removeEventListener('pv:share', onShare)
  }, [])

  useEffect(() => {
    if (!share) return
    const onDown = (e: MouseEvent) => {
      if (!shareRef.current?.contains(e.target as Node)) setShare(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [share])

  useEffect(() => {
    if (!exportMenu) return
    const onDown = (e: MouseEvent) => {
      if (!exportRef.current?.contains(e.target as Node)) setExportMenu(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [exportMenu])

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

  const item = (label: string, fn: () => Promise<unknown>, className?: string) => (
    <button
      role="menuitem"
      className={`quiet ${className ?? ''}`}
      onClick={() => {
        setMenu(false)
        void run(fn)
      }}
    >
      {label}
    </button>
  )

  return (
    <article className="detail">
      <header className="detail-head">
        {onBack && (
          <button className="back quiet" onClick={onBack}>
            ← All prompts
          </button>
        )}
        <div className="title-row">
          <h2>{prompt.title}</h2>
          <div className="toolbar">
            <div ref={exportRef} style={{ display: 'contents' }}>
              <button
                className="icon quiet"
                aria-label="Export this prompt"
                aria-haspopup="menu"
                aria-expanded={exportMenu}
                title="Export this prompt"
                onClick={() => setExportMenu((o) => !o)}
              >
                ⤓
              </button>
              {exportMenu && (
                <div
                  className="menu"
                  role="menu"
                  aria-label="Export this prompt"
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') {
                      setExportMenu(false)
                      exportRef.current?.querySelector<HTMLElement>('[aria-haspopup]')?.focus()
                    }
                  }}
                >
                  {['markdown', 'json'].map((fmt) => (
                    <button
                      key={fmt}
                      role="menuitem"
                      className="quiet"
                      onClick={async () => {
                        setExportMenu(false)
                        try {
                          const { blob, headers } = await api.exportPrompt(prompt.id, fmt, {
                            pretty: false,
                            bom: true,
                            raw: false,
                          })
                          const cd = headers.get('Content-Disposition')
                          const m = cd?.match(/filename="?([^";]+)"?/)
                          saveBlob(blob, m ? m[1] : `${prompt.title}.${fmt === 'markdown' ? 'md' : 'json'}`)
                        } catch (err) {
                          setError(err instanceof Error ? err.message : String(err))
                        }
                      }}
                    >
                      Export as {fmt === 'markdown' ? 'Markdown (.md)' : 'JSON'}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div ref={shareRef} style={{ display: 'contents' }}>
              <button
                className="icon quiet"
                aria-label="Share"
                aria-haspopup="dialog"
                aria-expanded={share}
                title="Share snippet"
                onClick={() => setShare((o) => !o)}
              >
                ⤴
              </button>
              {share && <SharePopover prompt={prompt} values={values} onClose={() => setShare(false)} />}
            </div>
            <button
              className="icon quiet"
              aria-label="Favorite"
              title={prompt.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
              aria-pressed={prompt.is_favorite}
              onClick={() =>
                run(async () => onChanged(await api.patchPrompt(prompt.id, { is_favorite: !prompt.is_favorite })))
              }
            >
              {prompt.is_favorite ? '★' : '☆'}
            </button>
            <button onClick={onEdit}>Edit</button>
            <div ref={menuRef} style={{ display: 'contents' }}>
              <button
                className="icon quiet"
                aria-label="More actions"
                aria-haspopup="menu"
                aria-expanded={menu}
                onClick={() => setMenu((o) => !o)}
              >
                ⋯
              </button>
              {menu && (
                <div
                  className="menu"
                  role="menu"
                  aria-label="More actions"
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') {
                      setMenu(false)
                      menuRef.current?.querySelector<HTMLElement>('[aria-haspopup]')?.focus()
                    }
                  }}
                >
                  {item('Duplicate', async () => onDuplicated(await api.duplicatePrompt(prompt.id)))}
                  {prompt.seed_modified &&
                    item('Reset to original', async () => onChanged(await api.resetPrompt(prompt.id)))}
                  {item(
                    'Move to trash',
                    async () => {
                      await api.deletePrompt(prompt.id)
                      onDeleted()
                    },
                    'danger',
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
        {prompt.description && <p className="lede">{prompt.description}</p>}
        <div className="subtitle">
          {prompt.category && <span>{prompt.category.name}</span>}
          <span>· {prompt.difficulty}</span>
          {prompt.tags.map((t) => (
            <button key={t} className="chip plain" onClick={() => onTag(t)}>
              #{t}
            </button>
          ))}
        </div>
      </header>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {prompt.disclaimer && (
        <p className="notice" role="note">
          <strong>Note: </strong>
          {prompt.disclaimer}
        </p>
      )}

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
        <div className="section-head">
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

      <section>
        <button
          className="quiet details-toggle"
          aria-expanded={details}
          aria-controls="prompt-details"
          onClick={() => setDetails((o) => !o)}
        >
          <span aria-hidden="true">{details ? '▾' : '▸'}</span> Details
        </button>
        {details && (
          <dl id="prompt-details" className="details-list">
            <dt>Source</dt>
            <dd>
              {prompt.seed_id ? 'Shipped prompt' : 'Your prompt'}
              {prompt.seed_modified ? ' (edited)' : ''}
            </dd>
            <dt>Used</dt>
            <dd>
              {prompt.use_count} time{prompt.use_count === 1 ? '' : 's'}
            </dd>
            <dt>Updated</dt>
            <dd>{new Date(prompt.updated_at).toLocaleDateString()}</dd>
            {prompt.model_hints && (
              <>
                <dt>Model hints</dt>
                <dd>{prompt.model_hints}</dd>
              </>
            )}
            {prompt.output_format && (
              <>
                <dt>Output format</dt>
                <dd>{prompt.output_format}</dd>
              </>
            )}
          </dl>
        )}
      </section>
    </article>
  )
}
