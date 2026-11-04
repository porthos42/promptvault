import { useOutletContext, useSearchParams } from 'react-router'
import ExportPanel from '../components/ExportPanel'
import ImportWizard from '../components/ImportWizard'
import CategoriesPanel from '../components/CategoriesPanel'
import type { ListQuery } from '../api'
import { readFilters } from './Library'
import type { ShellContext } from '../Shell'

/** The /data page: Export, Import and Categories tabs. The filters come from the URL, so
 *  "Export" launched from the library carries the active filters along. */
export default function Data() {
  const [sp, setSp] = useSearchParams()
  const { categories, bump } = useOutletContext<ShellContext>()
  const tab = ['import', 'categories'].includes(sp.get('tab') ?? '') ? sp.get('tab') : 'export'
  const f = readFilters(sp)
  const filters: ListQuery = {
    q: f.q,
    category: f.category,
    tags: f.tags,
    difficulty: f.difficulty,
    favorite: f.favorite ? 'true' : undefined,
  }
  const setTab = (t: 'export' | 'import' | 'categories') =>
    setSp((prev) => {
      const next = new URLSearchParams(prev)
      next.set('tab', t)
      if (t === 'export') next.delete('step')
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
        <button role="tab" id="tab-categories" aria-selected={tab === 'categories'} aria-controls="panel-categories" onClick={() => setTab('categories')}>
          Categories
        </button>
      </div>
      {tab === 'categories' ? (
        <section id="panel-categories" role="tabpanel" aria-labelledby="tab-categories" className="panel">
          <CategoriesPanel categories={categories} bump={bump} />
        </section>
      ) : tab === 'export' ? (
        <section id="panel-export" role="tabpanel" aria-labelledby="tab-export" className="panel">
          <ExportPanel filters={filters} />
        </section>
      ) : (
        <section id="panel-import" role="tabpanel" aria-labelledby="tab-import" className="panel">
          <ImportWizard bump={bump} />
        </section>
      )}
    </div>
  )
}
