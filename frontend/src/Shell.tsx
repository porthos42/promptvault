import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import type { Category } from './api'
import CommandPalette from './components/CommandPalette'
import { useCategories } from './lib/hooks'

export type ShellContext = { categories: Category[]; bump: () => void }

export default function Shell() {
  const [version, setVersion] = useState(0)
  const [palette, setPalette] = useState(false)
  const categories = useCategories(version)
  const location = useLocation()
  const active = new URLSearchParams(location.search).get('category')
  const onLibrary = !location.pathname.startsWith('/trash')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPalette((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const top = categories.filter((c) => !c.parent)
  const kids = (slug: string) => categories.filter((c) => c.parent === slug)
  const item = (c: Category, depth: number) => (
    <li key={c.slug} style={{ paddingLeft: depth * 12 }}>
      <NavLink
        to={`/?category=${c.slug}`}
        className={onLibrary && active === c.slug ? 'active' : undefined}
        end
      >
        <span>{c.name}</span>
        <span className="count">{c.prompt_count}</span>
      </NavLink>
    </li>
  )

  return (
    <div className="shell">
      <aside className="sidebar">
        <h1>Prompt Vault</h1>
        <NavLink to="/new" className="newbtn">
          + New prompt
        </NavLink>
        <button className="link" onClick={() => setPalette(true)}>
          Search all ( Ctrl+K )
        </button>
        <nav aria-label="Categories">
          <ul>
            <li>
              <NavLink to="/" className={onLibrary && !active ? 'active' : undefined} end>
                All prompts
              </NavLink>
            </li>
            {top.flatMap((c) => [item(c, 0), ...kids(c.slug).map((k) => item(k, 1))])}
            <li className="sep">
              <NavLink to="/trash">Trash</NavLink>
            </li>
          </ul>
        </nav>
      </aside>
      <main className="main">
        <Outlet context={{ categories, bump: () => setVersion((v) => v + 1) } satisfies ShellContext} />
      </main>
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
    </div>
  )
}
