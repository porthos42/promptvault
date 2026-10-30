import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useRef } from 'react'
import type { Prompt } from '../api'

const ROW_HEIGHT = 84

type Props = {
  items: Prompt[]
  hasMore: boolean
  selectedId?: string
  onSelect: (p: Prompt) => void
  onLoadMore: () => void
  actions?: (p: Prompt) => React.ReactNode
}

export default function PromptList({ items, hasMore, selectedId, onSelect, onLoadMore, actions }: Props) {
  const parentRef = useRef<HTMLDivElement>(null)
  const virt = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  })
  const rows = virt.getVirtualItems()
  const last = rows.length ? rows[rows.length - 1].index : -1

  useEffect(() => {
    if (hasMore && last >= items.length - 10) onLoadMore()
  }, [hasMore, last, items.length, onLoadMore])

  return (
    <div ref={parentRef} className="plist" role="listbox" aria-label="Prompts">
      <div style={{ height: virt.getTotalSize(), position: 'relative' }}>
        {rows.map((row) => {
          const p = items[row.index]
          return (
            <div
              key={p.id}
              role="option"
              aria-selected={p.id === selectedId}
              tabIndex={0}
              className="prow"
              data-selected={p.id === selectedId}
              style={{ height: ROW_HEIGHT, transform: `translateY(${row.start}px)` }}
              onClick={() => onSelect(p)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSelect(p)
              }}
            >
              <div className="prow-title">
                {p.is_favorite && <span aria-label="favorite">★ </span>}
                {p.title}
              </div>
              <div className="prow-desc">{p.description || p.body.slice(0, 120)}</div>
              <div className="prow-meta">
                {p.category && <span className="chip">{p.category.name}</span>}
                <span className="chip dim">{p.difficulty}</span>
                {p.tags.slice(0, 3).map((t) => (
                  <span key={t} className="chip dim">
                    #{t}
                  </span>
                ))}
                {actions && <span className="prow-actions">{actions(p)}</span>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
