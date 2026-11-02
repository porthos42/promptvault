import { useEffect, useRef, useState } from 'react'
import type { Category } from '../api'
import { useDebounced } from '../lib/hooks'

export type Filters = {
  q: string
  category: string
  tags: string[]
  difficulty: string
  sort: string
  favorite: boolean
}

type Props = {
  filters: Filters
  categories: Category[]
  total: number
  correctedQuery: string | null
  onChange: (patch: Partial<Filters>) => void
  onClear: () => void
}

const SORTS = [
  ['', 'Best match'],
  ['newest', 'Newest'],
  ['updated', 'Recently updated'],
  ['recent', 'Recently used'],
  ['popular', 'Most used'],
  ['rating', 'Top rated'],
  ['title', 'Title A-Z'],
] as const

function activeFilterCount(f: Filters): number {
  return (f.category ? 1 : 0) + (f.difficulty ? 1 : 0) + (f.favorite ? 1 : 0) + f.tags.length
}

export default function FilterBar({ filters, categories, total, correctedQuery, onChange, onClear }: Props) {
  const [text, setText] = useState(filters.q)
  const [panel, setPanel] = useState(false)
  const debounced = useDebounced(text, 150)
  const input = useRef<HTMLInputElement>(null)

  // Push the debounced text into the URL; adopt external changes (e.g. clear, back button).
  useEffect(() => {
    if (debounced !== filters.q) onChange({ q: debounced })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced])
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setText(filters.q)
  }, [filters.q])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      const typing = el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable
      if (e.key === '/' && !typing) {
        e.preventDefault()
        input.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const count = activeFilterCount(filters)
  const categoryName = categories.find((c) => c.slug === filters.category)?.name ?? filters.category
  const groups = categories.filter((c) => !c.parent)

  return (
    <div className="filterbar">
      <div className="filter-row">
        <input
          ref={input}
          type="search"
          aria-label="Search prompts"
          placeholder="Search prompts"
          title="Press / to search"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <div className="filter-row">
        <button
          className="filter-toggle"
          aria-expanded={panel}
          aria-controls="filter-panel"
          aria-label={count > 0 ? `Filters, ${count} active` : 'Filters'}
          onClick={() => setPanel((o) => !o)}
        >
          Filters
          {count > 0 && (
            <span className="badge" aria-hidden="true">
              {count}
            </span>
          )}
        </button>
        <select aria-label="Sort" value={filters.sort} onChange={(e) => onChange({ sort: e.target.value })}>
          {SORTS.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {panel && (
        <div id="filter-panel" className="filter-panel">
          <label>
            Category
            <select
              aria-label="Category"
              value={filters.category}
              onChange={(e) => onChange({ category: e.target.value })}
            >
              <option value="">All categories</option>
              {groups.map((g) => {
                const kids = categories.filter((c) => c.parent === g.slug)
                return kids.length === 0 ? (
                  <option key={g.slug} value={g.slug}>
                    {g.name}
                  </option>
                ) : (
                  <optgroup key={g.slug} label={g.name}>
                    <option value={g.slug}>All {g.name}</option>
                    {kids.map((c) => (
                      <option key={c.slug} value={c.slug}>
                        {c.name}
                      </option>
                    ))}
                  </optgroup>
                )
              })}
            </select>
          </label>
          <label>
            Difficulty
            <select
              aria-label="Difficulty"
              value={filters.difficulty}
              onChange={(e) => onChange({ difficulty: e.target.value })}
            >
              <option value="">Any difficulty</option>
              <option value="beginner">Beginner</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </select>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={filters.favorite}
              onChange={(e) => onChange({ favorite: e.target.checked })}
            />
            Favorites only
          </label>
        </div>
      )}
      <div className="chips">
        <span className="dim" aria-live="polite">
          {total} prompt{total === 1 ? '' : 's'}
        </span>
        {filters.category && (
          <button
            className="chip"
            aria-label={`Remove category ${categoryName}`}
            onClick={() => onChange({ category: '' })}
          >
            {categoryName} ×
          </button>
        )}
        {filters.difficulty && (
          <button
            className="chip"
            aria-label={`Remove difficulty ${filters.difficulty}`}
            onClick={() => onChange({ difficulty: '' })}
          >
            {filters.difficulty} ×
          </button>
        )}
        {filters.favorite && (
          <button className="chip" aria-label="Remove favorites filter" onClick={() => onChange({ favorite: false })}>
            Favorites ×
          </button>
        )}
        {filters.tags.map((t) => (
          <button
            key={t}
            className="chip"
            aria-label={`Remove tag ${t}`}
            onClick={() => onChange({ tags: filters.tags.filter((x) => x !== t) })}
          >
            #{t} ×
          </button>
        ))}
        {correctedQuery && <span className="dim">Showing results for “{correctedQuery}”</span>}
        {(count > 0 || filters.q) && (
          <button className="link" onClick={onClear}>
            Clear all
          </button>
        )}
      </div>
    </div>
  )
}
