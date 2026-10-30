import { useState } from 'react'
import { api } from '../api'
import PromptList from '../components/PromptList'
import { usePromptFeed } from '../lib/hooks'

export default function Trash() {
  const feed = usePromptFeed({ trash: 'true', sort: 'updated' })
  const [error, setError] = useState<string | null>(null)

  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      feed.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="trash">
      <header className="page-head">
        <h2>Trash</h2>
        <span className="dim">{feed.total} item{feed.total === 1 ? '' : 's'}. Trash is purged after 30 days.</span>
        <button
          disabled={feed.total === 0}
          onClick={() => {
            if (window.confirm('Permanently delete everything in Trash?')) void act(() => api.emptyTrash())
          }}
        >
          Empty trash
        </button>
      </header>
      {(error || feed.error) && (
        <p role="alert" className="error">
          {error ?? feed.error}
        </p>
      )}
      {!feed.loading && feed.items.length === 0 && <p className="empty">Trash is empty.</p>}
      <PromptList
        items={feed.items}
        hasMore={feed.hasMore}
        onLoadMore={feed.loadMore}
        onSelect={() => undefined}
        actions={(p) => (
          <>
            <button
              onClick={(e) => {
                e.stopPropagation()
                void act(() => api.restorePrompt(p.id))
              }}
            >
              Restore
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation()
                if (window.confirm(`Permanently delete "${p.title}"?`))
                  void act(() => api.deletePrompt(p.id, true))
              }}
            >
              Delete forever
            </button>
          </>
        )}
      />
    </div>
  )
}
