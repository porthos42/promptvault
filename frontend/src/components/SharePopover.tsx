import { useEffect, useRef, useState } from 'react'
import { api, type Prompt } from '../api'

const FORMATS = [
  ['markdown', 'Markdown'],
  ['text', 'Plain text'],
  ['json', 'JSON'],
] as const

type Props = { prompt: Prompt; values: Record<string, string>; onClose: () => void }

/** Share snippet popover: format switch, current variable values, missing hint and copy. */
export default function SharePopover({ prompt, values, onClose }: Props) {
  const [format, setFormat] = useState<(typeof FORMATS)[number][0]>('markdown')
  const [text, setText] = useState('')
  const [missing, setMissing] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    box.current?.querySelector<HTMLElement>('input:checked')?.focus()
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onClose is only a cleanup action; the effect must run once
  }, [])

  useEffect(() => {
    let live = true
    const vals = Object.entries(values)
      .filter(([, v]) => v !== '')
      .map(([k, v]) => `${k}=${v}`)
    api
      .sharePrompt(prompt.id, format, vals)
      .then((r) => {
        if (!live) return
        setText(r.text)
        setMissing(r.missing)
        setError(null)
      })
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onClose is a new closure each render; it is only a cleanup action
  }, [format, prompt.id, values])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
      box.current?.parentElement?.querySelector<HTMLElement>('[aria-haspopup="dialog"]')?.focus()
    } else if (e.key === 'Tab') {
      // Small focus trap: keep Tab inside the popover.
      const items = [...box.current!.querySelectorAll<HTMLElement>('button, input, [href]')]
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="menu share" role="dialog" aria-label="Share prompt" ref={box} onKeyDown={onKeyDown}>
      <div role="radiogroup" aria-label="Share format" className="fmt-switch">
        {FORMATS.map(([f, label]) => (
          <label key={f} className="check">
            <input
              type="radio"
              name="share-format"
              value={f}
              checked={format === f}
              onChange={() => setFormat(f)}
            />
            {label}
          </label>
        ))}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {missing.length > 0 && (
        <p className="notice dim">
          <strong>Missing: </strong>
          {missing.join(', ')} — fill them in the variable form for the snippet with values.
        </p>
      )}
      <pre className="preview" data-testid="share-preview">
        {text || (error ? '' : 'Loading...')}
      </pre>
      <button className="primary" onClick={() => void copy()}>
        {copied ? 'Copied ✓' : 'Copy snippet'}
      </button>
    </div>
  )
}
