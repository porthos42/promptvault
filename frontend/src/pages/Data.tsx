import { useSearchParams } from 'react-router'
import ExportPanel from '../components/ExportPanel'
import type { ListQuery } from '../api'
import { readFilters } from './Library'

/** The /data page: Export and Import tabs. The filters come from the URL, so
 *  "Export" launched from the library carries the active filters along. */
export default function Data() {
  const [sp, setSp] = useSearchParams()
  const tab = sp.get('tab') === 'import' ? 'import' : 'export'
  const f = readFilters(sp)
  const filters: ListQuery = {
    q: f.q,
    category: f.category,
    tags: f.tags,
    difficulty: f.difficulty,
    favorite: f.favorite ? 'true' : undefined,
  }
  const setTab = (t: 'export' | 'import') => setSp((prev) => {
    const next = new URLSearchParams(prev)
    next.set('tab', t)
    return next
  })

  return (
    <div className="data page">
      <header className="page-head">
        <h2>Data</h2>
        <span className="dim">Download your library or bring data in. Exports are ordered by title.</span>
      </header>
      <div role="tablist" aria-label="Data" className="tabs">
        <button role="tab" id="tab-export" aria-selected={tab === 'export'} aria-controls="panel-export" onClick={() => setTab('export')}>
          Export
        </button>
        <button role="tab" id="tab-import" aria-selected={tab === 'import'} aria-controls="panel-import" onClick={() => setTab('import')}>
          Import
        </button>
      </div>
      {tab === 'export' ? (
        <section id="panel-export" role="tabpanel" aria-labelledby="tab-export" className="panel">
          <ExportPanel filters={filters} />
        </section>
      ) : (
        <section id="panel-import" role="tabpanel" aria-labelledby="tab-import" className="panel">
          <p className="empty">Import lands with the next release (files, pastes and repositories).</p>
        </section>
      )}
    </div>
  )
}
