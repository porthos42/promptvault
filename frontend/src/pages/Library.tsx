import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useOutletContext, useParams, useSearchParams } from 'react-router'
import { api, type Prompt } from '../api'
import FilterBar, { type Filters } from '../components/FilterBar'
import PromptDetail from '../components/PromptDetail'
import PromptList from '../components/PromptList'
import { usePromptFeed } from '../lib/hooks'
import type { ShellContext } from '../Shell'

export function readFilters(sp: URLSearchParams): Filters {
  return {
    q: sp.get('q') ?? '',
    category: sp.get('category') ?? '',
    tags: sp.getAll('tags'),
    difficulty: sp.get('difficulty') ?? '',
    sort: sp.get('sort') ?? '',
    favorite: sp.get('favorite') === 'true',
  }
}

export function writeFilters(f: Filters): URLSearchParams {
  const sp = new URLSearchParams()
  if (f.q) sp.set('q', f.q)
  if (f.category) sp.set('category', f.category)
  for (const t of f.tags) sp.append('tags', t)
  if (f.difficulty) sp.set('difficulty', f.difficulty)
  if (f.sort) sp.set('sort', f.sort)
  if (f.favorite) sp.set('favorite', 'true')
  return sp
}

export default function Library() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [sp, setSp] = useSearchParams()
  const { categories, bump } = useOutletContext<ShellContext>()
  const filters = useMemo(() => readFilters(sp), [sp])
  const search = sp.toString()

  const feed = usePromptFeed({
    q: filters.q,
    category: filters.category,
    tags: filters.tags,
    difficulty: filters.difficulty,
    sort: filters.sort,
    favorite: filters.favorite ? 'true' : undefined,
  })

  const [selected, setSelected] = useState<Prompt | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  useEffect(() => {
    if (!id) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelected(null)
      return
    }
    let live = true
    setDetailError(null)
    api
      .getPrompt(id)
      .then((p) => live && setSelected(p))
      .catch((e: unknown) => {
        if (!live) return
        setSelected(null)
        setDetailError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      live = false
    }
  }, [id])

  const change = useCallback(
    (patch: Partial<Filters>) =>
      setSp((prev) => writeFilters({ ...readFilters(prev), ...patch }), { replace: true }),
    [setSp],
  )
  const refresh = () => {
    feed.reload()
    bump()
  }

  return (
    <div className="library">
      <section className="list-pane">
        <FilterBar
          filters={filters}
          categories={categories}
          total={feed.total}
          correctedQuery={feed.correctedQuery}
          onChange={change}
          onClear={() => setSp({}, { replace: true })}
        />
        {feed.error && (
          <p role="alert" className="error">
            {feed.error}
          </p>
        )}
        {!feed.loading && !feed.error && feed.items.length === 0 && (
          <p className="empty">No prompts match. Try clearing filters.</p>
        )}
        <PromptList
          items={feed.items}
          hasMore={feed.hasMore}
          selectedId={id}
          onLoadMore={feed.loadMore}
          onSelect={(p) => navigate({ pathname: `/p/${p.id}`, search })}
        />
      </section>
      <section className="detail-pane">
        {detailError && (
          <p role="alert" className="error">
            {detailError}
          </p>
        )}
        {selected ? (
          <PromptDetail
            key={selected.id}
            prompt={selected}
            onChanged={(p) => {
              if (p) setSelected(p)
              refresh()
            }}
            onTag={(t) => change({ tags: filters.tags.includes(t) ? filters.tags : [...filters.tags, t] })}
            onEdit={() => navigate(`/p/${selected.id}/edit`)}
            onDuplicated={(p) => {
              refresh()
              navigate({ pathname: `/p/${p.id}`, search })
            }}
            onDeleted={() => {
              refresh()
              navigate({ pathname: '/', search })
            }}
          />
        ) : (
          !detailError && <p className="empty">Select a prompt to view, fill variables and copy.</p>
        )}
      </section>
    </div>
  )
}
