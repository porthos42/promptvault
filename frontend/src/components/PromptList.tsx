import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useRef } from 'react'
import type { Prompt } from '../api'

// Fixed row heights keep the virtualizer cheap: title + description + one meta line (+ an action line in Trash).
const ROW_HEIGHT = 84
const ROW_HEIGHT_WITH_ACTIONS = 128
const MAX_TAGS = 2

type Props = {
  items: Prompt[]
  hasMore: boolean
  selectedId?: string
  onSelect: (p: Prompt) => void
  onLoadMore: () => void
  actions?: (p: Prompt) => React.ReactNode
}

function metaLine(p: Prompt): string {
  const tags = p.tags.slice(0, MAX_TAGS).map((t) => `#${t}`)
  const extra = p.tags.length - MAX_TAGS
  return [p.category?.name, p.difficulty, [...tags, extra > 0 ? `+${extra}` : ''].filter(Boolean).join(' ')]
    .filter(Boolean)
    .join(' · ')
}

export default function PromptList({ items, hasMore, selectedId, onSelect, onLoadMore, actions }: Props) {
  const parentRef = useRef<HTMLDivElement>(null)
  const rowHeight = actions ? ROW_HEIGHT_WITH_ACTIONS : ROW_HEIGHT
  const virt = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
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
              style={{ height: rowHeight - 4, transform: `translateY(${row.start}px)` }}
              onClick={() => onSelect(p)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSelect(p)
              }}
            >
              <div className="prow-title">
                <span>{p.title}</span>
                {p.is_favorite && (
                  <span className="fav" role="img" aria-label="favorite">
                    ★
                  </span>
                )}
              </div>
              <div className="prow-desc">{p.description || p.body.slice(0, 120)}</div>
              <div className="prow-meta">{metaLine(p)}</div>
              {actions && <div className="prow-actions">{actions(p)}</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
