import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Category, type ListQuery, type Prompt } from '../api'

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export type PromptFeed = {
  items: Prompt[]
  total: number
  loading: boolean
  error: string | null
  hasMore: boolean
  correctedQuery: string | null
  loadMore: () => void
  reload: () => void
}

/** Cursor-paginated prompt list; refetches from scratch whenever `query` changes. */
export function usePromptFeed(query: ListQuery): PromptFeed {
  const key = JSON.stringify(query)
  const [state, setState] = useState<{
    items: Prompt[]
    total: number
    cursor: string | null
    corrected: string | null
    loading: boolean
    error: string | null
  }>({ items: [], total: 0, cursor: null, corrected: null, loading: true, error: null })
  const gen = useRef(0)
  const busy = useRef(false)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    const id = ++gen.current
    busy.current = true
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState((s) => ({ ...s, loading: true, error: null }))
    api
      .listPrompts({ ...(JSON.parse(key) as ListQuery), limit: '50' })
      .then((r) => {
        if (id !== gen.current) return
        setState({
          items: r.items,
          total: r.total,
          cursor: r.next_cursor,
          corrected: r.corrected_query,
          loading: false,
          error: null,
        })
      })
      .catch((e: unknown) => {
        if (id !== gen.current) return
        setState((s) => ({
          ...s,
          items: [],
          total: 0,
          cursor: null,
          loading: false,
          error: e instanceof Error ? e.message : String(e),
        }))
      })
      .finally(() => {
        if (id === gen.current) busy.current = false
      })
  }, [key, nonce])

  const cursor = state.cursor
  const loadMore = useCallback(() => {
    if (!cursor || busy.current) return
    const id = gen.current
    busy.current = true
    api
      .listPrompts({ ...(JSON.parse(key) as ListQuery), limit: '50', cursor })
      .then((r) => {
        if (id !== gen.current) return
        setState((s) => ({
          ...s,
          items: [...s.items, ...r.items],
          cursor: r.next_cursor,
        }))
      })
      .catch((e: unknown) => {
        if (id !== gen.current) return
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }))
      })
      .finally(() => {
        if (id === gen.current) busy.current = false
      })
  }, [cursor, key])

  return {
    items: state.items,
    total: state.total,
    loading: state.loading,
    error: state.error,
    hasMore: state.cursor !== null,
    correctedQuery: state.corrected,
    loadMore,
    reload: () => setNonce((n) => n + 1),
  }
}

export function useCategories(refreshKey: unknown): Category[] {
  const [cats, setCats] = useState<Category[]>([])
  useEffect(() => {
    let live = true
    api
      .categories()
      .then((c) => live && setCats(c))
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [refreshKey])
  return cats
}
