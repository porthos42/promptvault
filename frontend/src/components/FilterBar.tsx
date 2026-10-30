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

export default function FilterBar({ filters, categories, total, correctedQuery, onChange, onClear }: Props) {
  const [text, setText] = useState(filters.q)
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

  const active =
    filters.q || filters.category || filters.tags.length || filters.difficulty || filters.favorite

  return (
    <div className="filterbar">
      <div className="filter-row">
        <input
          ref={input}
          type="search"
          aria-label="Search prompts"
          placeholder="Search prompts  ( / )"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <select
          aria-label="Category"
          value={filters.category}
          onChange={(e) => onChange({ category: e.target.value })}
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.name}
            </option>
          ))}
        </select>
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
        <select aria-label="Sort" value={filters.sort} onChange={(e) => onChange({ sort: e.target.value })}>
          {SORTS.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
        <label className="check">
          <input
            type="checkbox"
            checked={filters.favorite}
            onChange={(e) => onChange({ favorite: e.target.checked })}
          />
          Favorites
        </label>
      </div>
      <div className="filter-row dim">
        <span aria-live="polite">
          {total} prompt{total === 1 ? '' : 's'}
        </span>
        {filters.tags.map((t) => (
          <button
            key={t}
            className="chip removable"
            aria-label={`Remove tag ${t}`}
            onClick={() => onChange({ tags: filters.tags.filter((x) => x !== t) })}
          >
            #{t} ×
          </button>
        ))}
        {correctedQuery && <span>Showing results for “{correctedQuery}”</span>}
        {active && (
          <button className="link" onClick={onClear}>
            Clear filters
          </button>
        )}
      </div>
    </div>
  )
}
