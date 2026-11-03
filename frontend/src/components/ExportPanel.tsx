import { useEffect, useState } from 'react'
import { api, ApiError, type ExportFormat, type ListQuery } from '../api'
import { filenameFromDisposition, saveBlob } from '../lib/download'

type Props = { filters: ListQuery }

const NUM = (h: Headers, k: string): string | null => {
  const v = h.get(k)
  return v && v !== '0' ? v : null
}

export default function ExportPanel({ filters }: Props) {
  const [formats, setFormats] = useState<ExportFormat[] | null>(null)
  const [format, setFormat] = useState<string | null>(null)
  const [trashed, setTrashed] = useState(false)
  const [options, setOptions] = useState(false)
  const [pretty, setPretty] = useState(false)
  const [bom, setBom] = useState(true)
  const [raw, setRaw] = useState(false)
  const [whole, setWhole] = useState(false)
  const [total, setTotal] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

  const hasFilters = Object.keys(filters).some((k) => {
    const v = filters[k]
    return Array.isArray(v) ? v.length > 0 : v !== undefined && v !== ''
  })
  const scopeFilters: ListQuery = whole ? {} : filters
  const scopeKey = JSON.stringify(scopeFilters)

  useEffect(() => {
    let live = true
    api
      .exportFormats()
      .then((f) => {
        if (!live) return
        setFormats(f)
        if (!f.some((x) => x.name === format) && f.length) setFormat(f[0].name)
      })
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once; the format default survives a re-render
  }, [])

  // Live count for the scope summary (one cheap list call, no rows loaded).
  useEffect(() => {
    let live = true
    api
      .listPrompts({ ...scopeFilters, limit: '1' })
      .then((r) => live && setTotal(r.total))
      .catch(() => live && setTotal(null))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refetch only when the scope actually changes
  }, [scopeKey])

  const selected = formats?.find((f) => f.name === format)

  // The backend validates literal fields: drop empty strings/arrays before sending.
  const payloadFilters = Object.fromEntries(
    Object.entries(scopeFilters).filter(([, v]) =>
      Array.isArray(v) ? v.length > 0 : v !== undefined && v !== '',
    ),
  )

  const download = async () => {
    if (!format || busy) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const { blob, headers } = await api.exportDownload({
        format,
        filters: payloadFilters as Record<string, unknown>,
        include_trashed: trashed,
        pretty,
        bom,
        raw,
      })
      const name =
        filenameFromDisposition(headers.get('Content-Disposition')) ?? `promptvault-export.${selected?.extension ?? 'json'}`
      saveBlob(blob, name)
      const count = NUM(headers, 'X-Export-Count')
      const parts = [
        name,
        count ? `${count} prompt${count === '1' ? '' : 's'}` : null,
        NUM(headers, 'X-Export-Missing') && `${headers.get('X-Export-Missing')} id(s) not found`,
        headers.get('X-Export-Warnings') && `${headers.get('X-Export-Warnings')} warning(s) — see the file's Notes sheet`,
      ].filter(Boolean)
      setResult(parts.join(' — '))
    } catch (e) {
      if (e instanceof ApiError) setError(e.message)
      else setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="export">
      {formats && (
        <fieldset className="fmt-cards">
          <legend>Format</legend>
          <div role="radiogroup" aria-label="Export format">
            {formats.map((f) => (
              <label key={f.name} className={`fmt-card${f.name === format ? ' picked' : ''}`} data-unavailable={f.available ? undefined : ''}>
                <input
                  type="radio"
                  name="export-format"
                  value={f.name}
                  checked={f.name === format}
                  disabled={!f.available}
                  onChange={() => setFormat(f.name)}
                />
                <strong>
                  {f.name.toUpperCase()} <span className="dim small">.{f.extension}</span>
                </strong>
                <span className="small">{f.available ? f.description : f.reason}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      <fieldset className="scope">
        <legend>Scope</legend>
        <label className="check">
          <input type="radio" name="scope" checked={!whole} onChange={() => setWhole(false)} disabled={!hasFilters} />
          Current filters{hasFilters ? '' : ' (none set — the whole library)'}
        </label>
        <label className="check">
          <input type="radio" name="scope" checked={whole} onChange={() => setWhole(true)} />
          Whole library
        </label>
        <p className="dim" aria-live="polite">
          {total === null ? 'Counting…' : `${total} prompt${total === 1 ? '' : 's'} selected`}
        </p>
        <label className="check">
          <input type="checkbox" checked={trashed} onChange={(e) => setTrashed(e.target.checked)} />
          Include trash
        </label>
      </fieldset>

      <button className="quiet details-toggle" aria-expanded={options} aria-controls="export-options" onClick={() => setOptions((o) => !o)}>
        <span aria-hidden="true">{options ? '▾' : '▸'}</span> Options
      </button>
      {options && (
        <fieldset id="export-options" className="opt">
          <label className="check">
            <input type="checkbox" checked={pretty} onChange={(e) => setPretty(e.target.checked)} />
            Pretty JSON (indented)
          </label>
          <label className="check">
            <input type="checkbox" checked={bom} onChange={(e) => setBom(e.target.checked)} />
            CSV byte order mark (BOM)
          </label>
          <label className="check">
            <input type="checkbox" checked={raw} onChange={(e) => setRaw(e.target.checked)} />
            Raw CSV/XLSX (no formula guard)
          </label>
        </fieldset>
      )}

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {result && (
        <p role="status" className="dim" aria-live="polite">
          Saved {result}
        </p>
      )}

      <button className="primary" onClick={() => void download()} disabled={busy || !selected?.available}>
        {busy ? 'Downloading…' : 'Download'}
      </button>
    </div>
  )
}
