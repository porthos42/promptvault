import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { api, type Prompt } from '../api'
import { useDebounced } from '../lib/hooks'

export default function CommandPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const location = useLocation()
  const onPrompt = /^\/p\/[^/]+$/.test(location.pathname)
  const [q, setQ] = useState('')
  const [items, setItems] = useState<Prompt[]>([])
  const [active, setActive] = useState(0)
  const dq = useDebounced(q, 150)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => input.current?.focus(), [])

  useEffect(() => {
    let live = true
    api
      .listPrompts({ q: dq, limit: '8', sort: dq ? undefined : 'recent' })
      .then((r) => {
        if (!live) return
        setItems(r.items)
        setActive(0)
      })
      .catch(() => live && setItems([]))
    return () => {
      live = false
    }
  }, [dq])

  const open = (p: Prompt) => {
    navigate(`/p/${p.id}`)
    onClose()
  }

  const commands = (
    <div className="cmd-list">
      <button
        className="cmd"
        onClick={() => {
          navigate('/data?tab=export')
          onClose()
        }}
      >
        Export library
        <span className="dim small">Data · Export</span>
      </button>
      <button
        className="cmd"
        disabled={!onPrompt}
        title={onPrompt ? undefined : 'Open a prompt first'}
        onClick={() => {
          if (!onPrompt) return
          window.dispatchEvent(new Event('pv:share'))
          onClose()
        }}
      >
        Share prompt
        <span className="dim small">{onPrompt ? 'the open prompt' : 'no prompt open'}</span>
      </button>
    </div>
  )

  return (
    <div className="overlay" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose()
          else if (e.key === 'ArrowDown') {
            e.preventDefault()
            setActive((a) => Math.min(a + 1, items.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setActive((a) => Math.max(a - 1, 0))
          } else if (e.key === 'Enter' && items[active]) open(items[active])
        }}
      >
        <input
          ref={input}
          aria-label="Search prompts"
          placeholder="Jump to a prompt..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {commands}
        <ul role="listbox">
          {items.map((p, i) => (
            <li
              key={p.id}
              role="option"
              aria-selected={i === active}
              data-active={i === active}
              onMouseEnter={() => setActive(i)}
              onClick={() => open(p)}
            >
              <strong>{p.title}</strong>
              <span className="dim small">{p.category?.name}</span>
            </li>
          ))}
          {items.length === 0 && <li className="dim">No results</li>}
        </ul>
        <p className="palette-hint dim">↑↓ to move, Enter to open, Esc to close</p>
      </div>
    </div>
  )
}
