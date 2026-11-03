import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import type { Category } from './api'
import CommandPalette from './components/CommandPalette'
import { useCategories } from './lib/hooks'

export type ShellContext = { categories: Category[]; bump: () => void }

export default function Shell() {
  const [version, setVersion] = useState(0)
  const [palette, setPalette] = useState(false)
  const [navOpen, setNavOpen] = useState(false)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const categories = useCategories(version)
  const location = useLocation()
  const active = new URLSearchParams(location.search).get('category')
  const onLibrary =
    !location.pathname.startsWith('/trash') &&
    !location.pathname.startsWith('/data') &&
    !/^\/(new|p\/[^/]+\/edit)$/.test(location.pathname)

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

  // Derived state while rendering: close the mobile drawer on navigation and expand the active group.
  const [navKey, setNavKey] = useState(location.key)
  if (navKey !== location.key) {
    setNavKey(location.key)
    setNavOpen(false)
  }
  const activeCat = categories.find((c) => c.slug === active)
  const activeGroup = activeCat ? (activeCat.parent ?? activeCat.slug) : null
  const [seenGroup, setSeenGroup] = useState<string | null>(null)
  if (activeGroup !== seenGroup) {
    setSeenGroup(activeGroup)
    if (activeGroup) setOpen((s) => new Set(s).add(activeGroup))
  }

  const toggle = (slug: string) =>
    setOpen((s) => {
      const next = new Set(s)
      if (!next.delete(slug)) next.add(slug)
      return next
    })

  const link = (c: Category, className = 'navlink') => (
    <NavLink to={`/?category=${c.slug}`} className={() => (onLibrary && active === c.slug ? `${className} active` : className)} end>
      <span>{c.name}</span>
      <span className="count">{groupCount(c, categories)}</span>
    </NavLink>
  )

  const groups = categories.filter((c) => !c.parent)
  const kids = (slug: string) => categories.filter((c) => c.parent === slug)

  return (
    <div className="shell">
      <header className="topbar">
        <button
          className="icon quiet"
          aria-label="Open navigation"
          aria-expanded={navOpen}
          aria-controls="sidebar"
          onClick={() => setNavOpen(true)}
        >
          ☰
        </button>
        <strong>Prompt Vault</strong>
        <button className="icon quiet" aria-label="Search all prompts" onClick={() => setPalette(true)}>
          ⌕
        </button>
      </header>
      <div className="backdrop" data-open={navOpen} onClick={() => setNavOpen(false)} />
      <aside
        id="sidebar"
        className="sidebar"
        data-open={navOpen}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setNavOpen(false)
        }}
      >
        <div className="brand-row">
          <h1>Prompt Vault</h1>
          <button className="icon quiet" aria-label="Quick jump (Ctrl+K)" title="Quick jump (Ctrl+K)" onClick={() => setPalette(true)}>
            ⌕
          </button>
        </div>
        <NavLink to="/new" className="newbtn primary">
          + New prompt
        </NavLink>
        <nav aria-label="Categories">
          <NavLink to="/" className={() => (onLibrary && !active ? 'navlink active' : 'navlink')} end>
            <span>All prompts</span>
          </NavLink>
          {groups.map((g) => {
            const children = kids(g.slug)
            if (children.length === 0) return <div key={g.slug}>{link(g)}</div>
            const expanded = open.has(g.slug)
            const panel = `group-${g.slug}`
            return (
              <div key={g.slug}>
                <div className="group-row">
                  <button
                    aria-expanded={expanded}
                    aria-controls={panel}
                    aria-label={`${expanded ? 'Collapse' : 'Expand'} ${g.name}`}
                    onClick={() => toggle(g.slug)}
                  >
                    <span className="chev" aria-hidden="true">
                      ›
                    </span>
                  </button>
                  {link(g, '')}
                </div>
                {expanded && (
                  <ul id={panel} className="subnav">
                    {children.map((c) => (
                      <li key={c.slug}>{link(c)}</li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
          <div className="nav-foot">
            <NavLink to="/data" className={() => (location.pathname.startsWith('/data') ? 'navlink active' : 'navlink')}>
              Data
            </NavLink>
            <NavLink to="/trash" className={() => (location.pathname.startsWith('/trash') ? 'navlink active' : 'navlink')}>
              Trash
            </NavLink>
          </div>
        </nav>
      </aside>
      <main className="main">
        <Outlet context={{ categories, bump: () => setVersion((v) => v + 1) } satisfies ShellContext} />
      </main>
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
    </div>
  )
}

function groupCount(c: Category, all: Category[]): number {
  return c.prompt_count + all.filter((k) => k.parent === c.slug).reduce((n, k) => n + k.prompt_count, 0)
}
