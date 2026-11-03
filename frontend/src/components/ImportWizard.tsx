import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useBlocker, useSearchParams } from 'react-router'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  api,
  ApiError,
  type DupAction,
  type ImportJob,
  type ImportPreview,
  type ImporterInfo,
  type PreviewRow,
} from '../api'
import {
  MAPPING_FIELDS,
  actionSummary,
  buildMapping,
  encodeBase64,
  knownHeaders,
  parseMappingNotes,
  rowAction,
  tooLarge,
  unconfirmedLicenseRows,
} from '../lib/import'
import {
  IMPORTER_NOTES,
  PRIVATE_HOST_HINT,
  SSRF_SENTENCE,
  URL_PLACEHOLDER,
  buildNetworkSource,
  detectImporter,
  hasFetchedNotes,
  isNetworkImporter,
  networkErrorText,
  parseFetchedNotes,
  type NetworkImporter,
  type UrlOptions,
} from '../lib/urlsource'

type Step = 'source' | 'mapping' | 'preview' | 'result'
const STEP_IDS: Step[] = ['source', 'mapping', 'preview', 'result']
const STEPS: { id: Step; label: string }[] = [
  { id: 'source', label: 'Source' },
  { id: 'mapping', label: 'Mapping' },
  { id: 'preview', label: 'Preview' },
  { id: 'result', label: 'Result' },
]
const POLL_MS = 500

/** Importers whose files travel as base64 (bigger on the wire) instead of text. */
const BINARY_IMPORTERS = new Set(['xlsx'])

/** The importer name as a network importer, or null when it is a local one. */
const netImporterOf = (name: string): NetworkImporter | null => (isNetworkImporter(name) ? (name as NetworkImporter) : null)
const TEXT_ACCEPT: Record<string, string> = {
  json: '.json,application/json',
  csv: '.csv,.tsv,text/csv',
  markdown: '.md,.markdown,.txt,.zip,text/markdown',
  xlsx: '.xlsx',
}

type SourceState = {
  importer: string
  filename: string | null
  text: string | null
  base64: string | null
  paste: string
  delimiter: string
  license: string
  sourceUrl: string
  mapping: Record<string, string>
  url: string
  options: UrlOptions
}

const EMPTY_SOURCE: SourceState = {
  importer: '',
  filename: null,
  text: null,
  base64: null,
  paste: '',
  delimiter: '',
  license: '',
  sourceUrl: '',
  mapping: {},
  url: '',
  options: { config: '', split: '', limit: '', mode: 'page' },
}

const errText = (e: unknown): string => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e))

/**
 * Watch a job: seed with one GET, then SSE with an automatic fallback to the
 * 500 ms polling the wizard used before. `done`/`failed` end the watch; a
 * stream error drops to polling; an unknown job id reports the miss once.
 */
function useJobWatcher(id: string | null, onJob: (j: ImportJob) => void, onMiss?: () => void): 'sse' | 'poll' {
  const onJobRef = useRef(onJob)
  const onMissRef = useRef(onMiss)
  useEffect(() => {
    onJobRef.current = onJob
    onMissRef.current = onMiss
  })
  const [transport, setTransport] = useState<'sse' | 'poll'>(() => (typeof EventSource === 'undefined' ? 'poll' : 'sse'))
  useEffect(() => {
    if (!id) return
    let dead = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let es: EventSource | null = null
    const finish = (j: ImportJob): boolean => {
      onJobRef.current(j)
      return j.status === 'done' || j.status === 'failed'
    }
    const poll = async () => {
      try {
        const j = await api.job(id)
        if (dead || finish(j)) return
      } catch {
        /* a transient poll failure is retried on the next tick */
      }
      if (!dead) timer = setTimeout(() => void poll(), POLL_MS)
    }
    const startPolling = () => {
      setTransport('poll')
      void poll()
    }
    const startStream = () => {
      if (typeof EventSource === 'undefined') {
        startPolling()
        return
      }
      es = new EventSource(`/api/v1/jobs/${id}/events`)
      for (const name of ['progress', 'done', 'failed'] as const) {
        es.addEventListener(name, (ev: MessageEvent<string>) => {
          try {
            onJobRef.current(JSON.parse(ev.data) as ImportJob)
            if (name !== 'progress' && es) es.close()
          } catch {
            /* a malformed event keeps the stream alive */
          }
        })
      }
      es.onerror = () => {
        es?.close()
        es = null
        if (!dead) startPolling()
      }
    }
    void (async () => {
      try {
        const j = await api.job(id)
        if (dead) return
        onJobRef.current(j)
        if (j.status === 'pending' || j.status === 'running') startStream()
      } catch {
        if (!dead && onMissRef.current) onMissRef.current()
      }
    })()
    return () => {
      dead = true
      es?.close()
      if (timer) clearTimeout(timer)
    }
  }, [id])
  return transport
}

export default function ImportWizard({ bump }: { bump: () => void }) {
  const [sp, setSp] = useSearchParams()
  const [source, setSource] = useState<SourceState>(EMPTY_SOURCE)
  const [importers, setImporters] = useState<ImporterInfo[] | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [job, setJob] = useState<ImportJob | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [chip, setChip] = useState<'all' | 'new' | 'duplicate' | 'invalid' | 'license'>('all')
  const [defaultAction, setDefaultAction] = useState<DupAction>('skip')
  const [actions, setActions] = useState<Record<string, DupAction>>({})
  const [confirmAll, setConfirmAll] = useState(false)
  const [confirmed, setConfirmed] = useState<Set<number>>(new Set())
  const [expanded, setExpanded] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  // Load the importer list once.
  useEffect(() => {
    let live = true
    api
      .importers()
      .then((list) => live && setImporters(list))
      .catch((e: unknown) => live && setError(errText(e)))
    return () => {
      live = false
    }
  }, [])

  const rawStep = sp.get('step')
  const step: Step =
    (preview !== null || job !== null) && rawStep !== 'source' && STEP_IDS.includes(rawStep as Step)
      ? (rawStep as Step)
      : 'source'
  const setStep = (next: Step) =>
    setSp(
      (prev) => {
        const url = new URLSearchParams(prev)
        url.set('step', next)
        return url
      },
      { replace: true },
    )

  // The source and preview live in memory: warn before a route change throws them away.
  useBlocker(({ currentLocation, nextLocation }) => {
    const leaving =
      preview !== null &&
      step !== 'result' &&
      currentLocation.pathname !== nextLocation.pathname &&
      currentLocation.pathname.startsWith('/data')
    return leaving && !window.confirm('Leave the import? The loaded source and preview will be lost.')
  })

  const pickImporter = (name: string) => {
    if (name === source.importer) return
    // The URL and its options survive importer switches: auto-detection and the
    // manual override both need them.
    setSource({
      ...EMPTY_SOURCE,
      importer: name,
      license: source.license,
      sourceUrl: source.sourceUrl,
      url: source.url,
      options: source.options,
    })
    setError(null)
  }

  const netImporter = netImporterOf(source.importer)

  // Typing in the URL field re-detects the importer; a click on another network
  // card is the manual override.
  const onUrlChange = (value: string) => {
    const detected = detectImporter(value)
    setSource((s) => ({ ...s, url: value, importer: isNetworkImporter(s.importer) && detected ? detected : s.importer }))
  }

  const setOptions = (patch: Partial<UrlOptions>) => setSource((s) => ({ ...s, options: { ...s.options, ...patch } }))

  const hasSource =
    netImporter !== null
      ? source.url.trim().length > 0
      : source.importer === 'clipboard'
        ? source.paste.trim().length > 0
        : source.text !== null || source.base64 !== null

  const readFile = async (file: File | undefined) => {
    if (!file) return
    setError(null)
    const binary = BINARY_IMPORTERS.has(source.importer) || /\.(xlsx|zip)$/i.test(file.name)
    if (tooLarge(file.size, binary)) {
      setError(
        `${file.name} is too large: the import request is capped at 5 MiB${binary ? ' (base64 encoding adds a third)' : ''}.`,
      )
      return
    }
    if (binary) {
      const buf = new Uint8Array(await file.arrayBuffer())
      setSource((s) => ({ ...s, filename: file.name, base64: encodeBase64(buf), text: null }))
    } else {
      const text = await file.text()
      setSource((s) => ({ ...s, filename: file.name, text, base64: null }))
    }
  }

  /** The source object the request will carry; shape depends on the importer. */
  const buildSourceFrom = (src: SourceState): Record<string, unknown> => {
    const net = netImporterOf(src.importer)
    if (net) return buildNetworkSource(net, src.url, src.options)
    if (src.importer === 'clipboard') {
      const out: Record<string, unknown> = { content: src.paste }
      if (src.delimiter.trim()) out.delimiter = src.delimiter.trim()
      return out
    }
    const out: Record<string, unknown> = {}
    if (src.base64 !== null) out.content_base64 = src.base64
    else if (src.text !== null) {
      out.content = src.text
      if (src.filename) out.name = src.filename
    }
    if (Object.keys(src.mapping).length) out.mapping = src.mapping
    return out
  }

  const defaultsOf = (src: SourceState) => ({
    ...(src.license.trim() ? { default_license: src.license.trim() } : {}),
    ...(src.sourceUrl.trim() ? { default_source_url: src.sourceUrl.trim() } : {}),
  })

  const runPreview = async (landOn: 'mapping' | 'preview', src: SourceState = source) => {
    if (!hasSource || busy) return
    setBusy(true)
    setError(null)
    try {
      const p = await api.importPreview({ importer: src.importer, source: buildSourceFrom(src), ...defaultsOf(src) })
      if (!alive.current) return
      setPreview(p)
      setActions({})
      setConfirmed(new Set())
      setConfirmAll(false)
      setExpanded(null)
      setChip('all')
      const notes = p.rows.length ? parseMappingNotes(p.rows[0].warnings) : { mapped: {}, ignored: [] as string[] }
      const hasNotes = Object.keys(notes.mapped).length > 0 || notes.ignored.length > 0
      setStep(hasNotes ? landOn : 'preview')
    } catch (e) {
      if (alive.current) setError(netImporterOf(src.importer) ? networkErrorText(e) : errText(e))
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  const applyMapping = (chosen: Record<string, string>) => {
    const mapping = buildMapping(chosen)
    const next: SourceState = { ...source, mapping }
    setSource(next)
    void runPreview('preview', next)
  }

  const commitBody = () => ({
    importer: source.importer,
    source: buildSourceFrom(source),
    ...defaultsOf(source),
    default_action: defaultAction,
    actions,
    confirm_license: confirmAll,
    confirmed_rows: [...confirmed],
  })

  const previewNotes = preview && preview.rows.length ? parseMappingNotes(preview.rows[0].warnings) : null
  const fetchedNotes = preview && preview.rows.length && netImporter ? parseFetchedNotes(preview.rows[0].warnings) : null
  const mappingApplies = previewNotes !== null && (Object.keys(previewNotes.mapped).length > 0 || previewNotes.ignored.length > 0)
  const summary = preview ? actionSummary(preview.rows, defaultAction, actions) : null
  const pendingLicense = preview ? unconfirmedLicenseRows(preview.rows, actions, defaultAction, confirmAll, confirmed) : []
  const actionable = summary ? summary.create + summary.replace + summary.keepBoth : 0

  // Job watching: SSE with fallback to polling. The job id stays in the URL, so a
  // reload resumes watching (the preview itself does not survive a reload).
  const [watchId, setWatchId] = useState<string | null>(null)
  const [fetchedOpen, setFetchedOpen] = useState(false)
  const previewRef = useRef(preview)
  const bumpRef = useRef(bump)
  const stepRef = useRef(setStep)
  useEffect(() => {
    previewRef.current = preview
    bumpRef.current = bump
    stepRef.current = setStep
  })
  const onJobUpdate = useCallback((j: ImportJob) => {
    if (!alive.current) return
    setJob(j)
    if (j.status === 'done') {
      bumpRef.current()
      stepRef.current('result')
    } else if (j.status === 'failed') {
      if (!previewRef.current) stepRef.current('result')
      setError(j.error ?? 'The import job failed.')
    }
  }, [])
  const resumeId = preview ? null : sp.get('job')
  const transport = useJobWatcher(watchId ?? resumeId, onJobUpdate, () =>
    setError('That import job is unknown. The server may have restarted since it was created.'),
  )

  /** One search-param update: the job id and (optionally) the step. Two replaces
   *  in one tick do not chain in react-router, so this must be a single call. */
  const setJobParam = (id: string, step: Step | null) =>
    setSp(
      (prev) => {
        const url = new URLSearchParams(prev)
        url.set('job', id)
        if (step) url.set('step', step)
        return url
      },
      { replace: true },
    )

  const commit = async () => {
    if (!preview || busy || pendingLicense.length > 0 || actionable === 0) return
    setBusy(true)
    setError(null)
    try {
      const j = await api.importCommit(commitBody())
      if (!alive.current) return
      setJob(j)
      if (j.status === 'pending' || j.status === 'running') {
        setJobParam(j.id, null)
        setWatchId(j.id)
      } else if (j.status === 'done') {
        bump()
        setJobParam(j.id, 'result')
      } else {
        setJobParam(j.id, null)
        setError(j.error ?? 'The import job failed.')
      }
    } catch (e) {
      if (alive.current) setError(errText(e))
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  const reset = () => {
    if (preview && !window.confirm('Start over? The loaded source and preview will be lost.')) return
    setSource(EMPTY_SOURCE)
    setPreview(null)
    setJob(null)
    setWatchId(null)
    setError(null)
    setSp(
      (prev) => {
        const url = new URLSearchParams(prev)
        url.delete('job')
        url.set('step', 'source')
        return url
      },
      { replace: true },
    )
  }

  const shown = useMemo(() => {
    if (!preview) return []
    if (chip === 'all') return preview.rows
    if (chip === 'license') return preview.rows.filter((r) => r.needs_license_confirm && r.status !== 'invalid')
    return preview.rows.filter((r) => r.status === chip)
  }, [preview, chip])

  if (step === 'result' && job) return <Result job={job} onAgain={reset} />

  return (
    <div className="import">
      <ol className="stepper" aria-label="Import steps">
        {STEPS.map((s, i) =>
          s.id === 'mapping' && !mappingApplies ? null : (
            <li key={s.id} aria-current={s.id === step ? 'step' : undefined} className={s.id === step ? 'current' : undefined}>
              {i + 1}. {s.label}
            </li>
          ),
        )}
      </ol>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      {!preview && resumeId && (
        <section aria-label="Import job progress" className="step-progress">
          {!job && <p className="dim">Loading job {resumeId}…</p>}
          {job && (job.status === 'pending' || job.status === 'running') && (
            <ProgressBlock
              job={job}
              transport={transport}
              note="Reloading this page resumes watching — the loaded preview itself does not survive a reload."
            />
          )}
        </section>
      )}

      {step === 'source' && (
        <section aria-label="Step 1: choose a source" className="step-source">
          {importers ? (
            <fieldset className="fmt-cards">
              <legend>Importer</legend>
              <div role="radiogroup" aria-label="Importer">
                {importers.map((imp) => (
                  <label
                    key={imp.name}
                    className={`fmt-card${imp.name === source.importer ? ' picked' : ''}`}
                    data-unavailable={imp.available ? undefined : ''}
                  >
                    <input
                      type="radio"
                      name="importer"
                      value={imp.name}
                      checked={imp.name === source.importer}
                      disabled={!imp.available}
                      onChange={() => pickImporter(imp.name)}
                    />
                    <strong>{imp.name}</strong>
                    <span className="small">{imp.available ? imp.description : imp.reason}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
            <p className="dim">Loading importers…</p>
          )}

          {netImporter && (
            <fieldset className="opt net-source">
              <legend>URL source</legend>
              <label className="inline-field">
                Address{' '}
                <input
                  type="url"
                  value={source.url}
                  onChange={(e) => onUrlChange(e.target.value)}
                  placeholder={URL_PLACEHOLDER[netImporter]}
                  aria-label="URL to import from"
                />
              </label>
              <p className="small dim">
                The importer is detected from the address (GitHub, Hugging Face, other pages); the cards above are the
                override.
              </p>
              <p className="small dim">{IMPORTER_NOTES[netImporter].can}</p>
              <p className="small dim">{IMPORTER_NOTES[netImporter].cannot}</p>
              <p className="small dim">
                {SSRF_SENTENCE} {PRIVATE_HOST_HINT}
              </p>
              {netImporter === 'huggingface' && (
                <div className="net-options">
                  <label className="inline-field">
                    Config{' '}
                    <input
                      type="text"
                      value={source.options.config}
                      onChange={(e) => setOptions({ config: e.target.value })}
                      placeholder="(auto)"
                    />
                  </label>
                  <label className="inline-field">
                    Split{' '}
                    <input
                      type="text"
                      value={source.options.split}
                      onChange={(e) => setOptions({ split: e.target.value })}
                      placeholder="train"
                    />
                  </label>
                  <label className="inline-field">
                    Row limit{' '}
                    <input
                      type="number"
                      min={1}
                      value={source.options.limit}
                      onChange={(e) => setOptions({ limit: e.target.value })}
                      placeholder="(up to the server limit)"
                    />
                  </label>
                </div>
              )}
              {netImporter === 'url' && (
                <label className="inline-field">
                  Mode{' '}
                  <select
                    aria-label="Page mode"
                    value={source.options.mode}
                    onChange={(e) => setOptions({ mode: e.target.value as 'page' | 'blocks' })}
                  >
                    <option value="page">One prompt per page (join the blocks)</option>
                    <option value="blocks">One prompt per block</option>
                  </select>
                </label>
              )}
              {netImporter === 'github' && (
                <p className="small dim">
                  A folder or file is part of the URL (/tree/&lt;branch&gt;/&lt;path&gt;); skipped files and truncation
                  are reported before the import.
                </p>
              )}
            </fieldset>
          )}

          {!netImporter && source.importer !== 'clipboard' && source.importer !== '' && (
            <div
              className={`dropzone${dragOver ? ' over' : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragOver(false)
                void readFile(e.dataTransfer.files[0])
              }}
            >
              <label className="file-label">
                {source.filename
                  ? `File: ${source.filename} — choose another or drop one here`
                  : 'Choose a file — or drop it here'}
                <input
                  type="file"
                  accept={TEXT_ACCEPT[source.importer] ?? ''}
                  onChange={(e) => void readFile(e.target.files?.[0])}
                />
              </label>
            </div>
          )}
          {source.importer === 'clipboard' && (
            <>
              <label className="paste-label">
                Paste your prompts (split several with a line of --- or ###)
                <textarea rows={8} value={source.paste} onChange={(e) => setSource((s) => ({ ...s, paste: e.target.value }))} />
              </label>
              <label className="inline-field">
                Delimiter (optional){' '}
                <input
                  type="text"
                  value={source.delimiter}
                  onChange={(e) => setSource((s) => ({ ...s, delimiter: e.target.value }))}
                  placeholder="---"
                />
              </label>
            </>
          )}

          <fieldset className="opt">
            <legend>Defaults for rows without their own</legend>
            <label className="inline-field">
              License{' '}
              <input
                type="text"
                list="license-suggestions"
                value={source.license}
                onChange={(e) => setSource((s) => ({ ...s, license: e.target.value }))}
                placeholder="CC-BY-4.0"
              />
            </label>
            <datalist id="license-suggestions">
              <option value="CC0-1.0" />
              <option value="CC-BY-4.0" />
              <option value="CC-BY-SA-4.0" />
              <option value="MIT" />
              <option value="Apache-2.0" />
              <option value="Unlicense" />
            </datalist>
            <label className="inline-field">
              Source URL{' '}
              <input
                type="text"
                value={source.sourceUrl}
                onChange={(e) => setSource((s) => ({ ...s, sourceUrl: e.target.value }))}
                placeholder="Where this came from"
              />
            </label>
          </fieldset>

          <div className="wizard-nav">
            <button className="primary" disabled={!source.importer || !hasSource || busy} onClick={() => void runPreview('mapping')}>
              {busy ? 'Reading…' : 'Next: check the data'}
            </button>
          </div>
        </section>
      )}

      {step === 'mapping' && preview && (
        <MappingStep
          preview={preview}
          onApply={applyMapping}
          onSkip={() => setStep('preview')}
          onBack={() => setStep('source')}
        />
      )}

      {step === 'preview' && preview && summary && (
        <section aria-label="Step 3: preview" className="step-preview">
          <p className="counters dim">
            {preview.total} row{preview.total === 1 ? '' : 's'}: {preview.new} new, {preview.duplicate} duplicate
            {preview.duplicate === 1 ? '' : 's'}, {preview.invalid} invalid
            {preview.needs_license_confirm ? `, ${preview.needs_license_confirm} need a license confirmation` : ''}
          </p>
          {fetchedNotes && hasFetchedNotes(fetchedNotes) && (
            <div className="fetched">
              <button aria-expanded={fetchedOpen} onClick={() => setFetchedOpen((o) => !o)}>
                What was fetched (
                {fetchedNotes.skipped.length + fetchedNotes.truncated.length + fetchedNotes.other.length} notes)
              </button>
              {fetchedOpen && (
                <ul>
                  {[...fetchedNotes.skipped, ...fetchedNotes.truncated, ...fetchedNotes.other].map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div role="group" aria-label="Filter rows by status" className="chips">
            {(
              [
                ['all', `All (${preview.total})`],
                ['new', `New (${preview.new})`],
                ['duplicate', `Duplicates (${preview.duplicate})`],
                ['invalid', `Invalid (${preview.invalid})`],
                ['license', `License (${preview.needs_license_confirm})`],
              ] as const
            ).map(([id, label]) => (
              <button key={id} aria-pressed={chip === id} onClick={() => setChip(id)}>
                {label}
              </button>
            ))}
          </div>

          {preview.total === 0 ? (
            <p className="empty">Nothing to import: the source parsed to zero prompts.</p>
          ) : (
            <PreviewTable
              rows={shown}
              defaultAction={defaultAction}
              actions={actions}
              setActions={setActions}
              confirmed={confirmed}
              setConfirmed={setConfirmed}
              expanded={expanded}
              setExpanded={setExpanded}
            />
          )}

          <fieldset className="opt">
            <legend>Duplicates</legend>
            <label className="inline-field">
              Default action{' '}
              <select value={defaultAction} onChange={(e) => setDefaultAction(e.target.value as DupAction)}>
                <option value="skip">Skip (keep the existing prompt)</option>
                <option value="replace">Replace the existing prompt</option>
                <option value="keep_both">Keep both</option>
              </select>
            </label>
          </fieldset>

          {preview.needs_license_confirm > 0 && (
            <fieldset className="opt license-gate">
              <legend>License</legend>
              <p className="small dim">
                {preview.needs_license_confirm} row{preview.needs_license_confirm === 1 ? '' : 's'} have no clear license. Confirm
                to import them; they are refused otherwise.
              </p>
              {netImporter && (
                <p className="small">
                  Where a row's license comes from: a GitHub import labels rows with the repository license — a repo
                  without a recognized license (or NOASSERTION) leaves rows unlabelled, so they trip this gate. Confirming
                  imports the rows with the default license above; make sure the source's terms allow that.
                </p>
              )}
              <label className="check">
                <input type="checkbox" checked={confirmAll} onChange={(e) => setConfirmAll(e.target.checked)} />
                Confirm all (import them with the chosen license)
              </label>
            </fieldset>
          )}

          {job && (job.status === 'pending' || job.status === 'running') && (
            <ProgressBlock job={job} transport={transport} note={null} />
          )}

          <div className="wizard-nav">
            <button className="quiet" onClick={() => setStep(mappingApplies ? 'mapping' : 'source')}>
              Back
            </button>
            <button
              className="primary"
              disabled={busy || actionable === 0 || pendingLicense.length > 0 || (job !== null && (job.status === 'pending' || job.status === 'running'))}
              onClick={() => void commit()}
            >
              {busy
                ? 'Importing…'
                : `Import: ${summary.create} new, ${summary.replace} replaced, ${summary.skip} skipped${
                    summary.keepBoth ? `, ${summary.keepBoth} kept both` : ''
                  }${summary.invalid ? `, ${summary.invalid} invalid skipped` : ''}`}
            </button>
          </div>
          {actionable === 0 && preview.total > 0 && (
            <p className="dim small">Nothing importable — every row is invalid or skipped.</p>
          )}
          {pendingLicense.length > 0 && (
            <p className="error small">
              Confirm the license for {pendingLicense.length} row{pendingLicense.length === 1 ? '' : 's'} to enable the import.
            </p>
          )}
          {job && job.status === 'failed' && <p className="small dim">The preview is kept — fix the problem and commit again.</p>}
        </section>
      )}

      <div className="wizard-nav">
        <button className="quiet" onClick={reset}>
          Start over
        </button>
      </div>
    </div>
  )
}

/** Live progress for a running job: bar, counters, and what the API cannot do. */
function ProgressBlock({ job, transport, note }: { job: ImportJob; transport: 'sse' | 'poll'; note: string | null }) {
  return (
    <div role="status" aria-live="polite" className="job-progress">
      <p>
        Importing… processed {job.processed} of {job.total} row{job.total === 1 ? '' : 's'}
      </p>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={job.total}
        aria-valuenow={job.processed}
      >
        <div
          className="progress-fill"
          style={{ width: `${job.total === 0 ? 0 : Math.round((job.processed / job.total) * 100)}%` }}
        />
      </div>
      <p className="counters dim small">
        {job.created} created, {job.replaced} replaced, {job.skipped} skipped, {job.invalid} invalid, {job.refused} refused
      </p>
      {transport === 'poll' && <p className="small dim">Live updates dropped — checking every half second instead.</p>}
      <p className="small dim">
        The import has no cancel: the job runs to completion on the server.{note ? ` ${note}` : ''}
      </p>
    </div>
  )
}

function MappingStep({
  preview,
  onApply,
  onSkip,
  onBack,
}: {
  preview: ImportPreview
  onApply: (chosen: Record<string, string>) => void
  onSkip: () => void
  onBack: () => void
}) {
  const notes = preview.rows.length ? parseMappingNotes(preview.rows[0].warnings) : { mapped: {}, ignored: [] as string[] }
  const headers = knownHeaders(notes)
  const [chosen, setChosen] = useState<Record<string, string>>(notes.mapped)
  return (
    <section aria-label="Step 2: column mapping" className="step-mapping">
      <p className="dim small">
        Columns detected in the first preview pass. Adjust the mapping and re-run the preview; columns marked “not imported”
        are ignored.
      </p>
      <table className="map-table" aria-label="Column mapping">
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">Column</th>
          </tr>
        </thead>
        <tbody>
          {MAPPING_FIELDS.map((field) => (
            <tr key={field}>
              <th scope="row">{field}</th>
              <td>
                <select
                  aria-label={`Column for ${field}`}
                  value={chosen[field] ?? ''}
                  onChange={(e) => setChosen((c) => ({ ...c, [field]: e.target.value }))}
                >
                  <option value="">(not imported)</option>
                  {headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="wizard-nav">
        <button className="quiet" onClick={onBack}>
          Back
        </button>
        <button onClick={onSkip}>Skip</button>
        <button className="primary" onClick={() => onApply(chosen)}>
          Re-run preview
        </button>
      </div>
    </section>
  )
}

type RowProps = {
  row: PreviewRow
  open: boolean
  onToggle: () => void
  defaultAction: DupAction
  actions: Record<string, DupAction>
  setActions: (fn: (a: Record<string, DupAction>) => Record<string, DupAction>) => void
  confirmed: Set<number>
  setConfirmed: (fn: (s: Set<number>) => Set<number>) => void
  dataIndex: number
}

function Row({
  row,
  open,
  onToggle,
  defaultAction,
  actions,
  setActions,
  confirmed,
  setConfirmed,
  dataIndex,
}: RowProps) {
  const match = row.match
  const inBatch = match != null && match.batch_index != null
  return (
    <>
      <tr data-index={dataIndex} className={open ? 'open' : undefined}>
        <td>{row.index + 1}</td>
        <td>
          <span className={`badge badge-${row.status}`}>
            {row.status === 'new' ? 'New' : row.status === 'duplicate' ? 'Duplicate' : 'Invalid'}
          </span>
          {row.needs_license_confirm && row.status !== 'invalid' && <span className="badge badge-license">License</span>}
        </td>
        <td>{row.draft.title || <span className="dim">(no title)</span>}</td>
        <td>{row.draft.category ?? ''}</td>
        <td>{row.draft.tags.join(', ')}</td>
        <td>
          <button aria-expanded={open} onClick={onToggle}>
            {open ? 'Hide' : 'Show'}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="detail-row">
          <td colSpan={6}>
            <dl>
              {row.errors.length > 0 && (
                <>
                  <dt>Errors</dt>
                  <dd>
                    <ul>
                      {row.errors.map((e) => (
                        <li key={e}>{e}</li>
                      ))}
                    </ul>
                  </dd>
                </>
              )}
              {row.warnings.length > 0 && (
                <>
                  <dt>Warnings</dt>
                  <dd>
                    <ul>
                      {row.warnings.map((w) => (
                        <li key={w}>{w}</li>
                      ))}
                    </ul>
                  </dd>
                </>
              )}
              {match && (
                <>
                  <dt>Duplicate of</dt>
                  <dd>
                    {match.kind === 'exact' ? 'Exact' : `Fuzzy (${Math.round(match.score * 100)}%)`} match:{' '}
                    {match.prompt_id ? (
                      <Link to={`/p/${match.prompt_id}`}>{match.title}</Link>
                    ) : (
                      `row ${(match.batch_index ?? 0) + 1} of this batch`
                    )}
                    {inBatch && ' — only Skip or Keep both applies to an in-batch duplicate'}
                  </dd>
                </>
              )}
              <dt>Body</dt>
              <dd>
                <pre className="draft-body">{row.draft.body.slice(0, 2000)}</pre>
              </dd>
            </dl>
            {row.status === 'duplicate' && !inBatch && (
              <label className="inline-field">
                Action{' '}
                <select
                  aria-label={`Action for row ${row.index + 1}`}
                  value={rowAction(row, defaultAction, actions)}
                  onChange={(e) => setActions((a) => ({ ...a, [String(row.index)]: e.target.value as DupAction }))}
                >
                  <option value="skip">Skip</option>
                  <option value="replace">Replace</option>
                  <option value="keep_both">Keep both</option>
                </select>
              </label>
            )}
            {row.needs_license_confirm && row.status !== 'invalid' && (
              <label className="check">
                <input
                  type="checkbox"
                  aria-label={`Confirm the license of row ${row.index + 1}`}
                  checked={confirmed.has(row.index)}
                  onChange={(e) =>
                    setConfirmed((s) => {
                      const next = new Set(s)
                      if (e.target.checked) next.add(row.index)
                      else next.delete(row.index)
                      return next
                    })
                  }
                />
                Confirm the license of this row
              </label>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

function PreviewTable(props: {
  rows: PreviewRow[]
  defaultAction: DupAction
  actions: Record<string, DupAction>
  setActions: (fn: (a: Record<string, DupAction>) => Record<string, DupAction>) => void
  confirmed: Set<number>
  setConfirmed: (fn: (s: Set<number>) => Set<number>) => void
  expanded: number | null
  setExpanded: (n: number | null) => void
}) {
  const parentRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line react/incompatible-library -- same pattern as PromptList
  const virt = useVirtualizer({
    count: props.rows.length,
    getScrollElement: () => parentRef.current,
    // The expanded detail row is taller; sizes are known up front, no per-row measuring.
    estimateSize: (i) => (props.expanded === props.rows[i].index ? 280 : 48),
    overscan: 8,
  })
  const items = virt.getVirtualItems()
  const Head = () => (
    <thead>
      <tr>
        <th scope="col">#</th>
        <th scope="col">Status</th>
        <th scope="col">Title</th>
        <th scope="col">Category</th>
        <th scope="col">Tags</th>
        <th scope="col">Details</th>
      </tr>
    </thead>
  )
  // The scroll element stays mounted even when the filter matches nothing, so the
  // virtualizer always has something to observe and recovers from an empty first paint.
  const head = items.length ? items[0].start : 0
  const tail = items.length ? Math.max(0, virt.getTotalSize() - items[items.length - 1].end) : 0
  return (
    <div className="preview-scroll" ref={parentRef}>
      <table className="preview-table" aria-label="Import preview">
        <Head />
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={6} className="empty">
                No rows match this filter.
              </td>
            </tr>
          ) : (
            <>
              {head > 0 && (
                <tr aria-hidden="true" style={{ height: head }}>
                  <td colSpan={6} />
                </tr>
              )}
              {items.map((item) => (
                <Row
                  key={item.key}
                  dataIndex={item.index}
                  row={props.rows[item.index]}
                  open={props.expanded === props.rows[item.index].index}
                  onToggle={() =>
                    props.setExpanded(props.expanded === props.rows[item.index].index ? null : props.rows[item.index].index)
                  }
                  defaultAction={props.defaultAction}
                  actions={props.actions}
                  setActions={props.setActions}
                  confirmed={props.confirmed}
                  setConfirmed={props.setConfirmed}
                />
              ))}
              {tail > 0 && (
                <tr aria-hidden="true" style={{ height: tail }}>
                  <td colSpan={6} />
                </tr>
              )}
            </>
          )}
        </tbody>
      </table>
    </div>
  )
}

function Result({ job, onAgain }: { job: ImportJob; onAgain: () => void }) {
  const firstCreated = job.results?.find((r) => r.outcome === 'created' && r.prompt_id)
  return (
    <section aria-label="Step 4: result" className="step-result">
      <h3>{job.status === 'done' ? 'Import complete' : 'Import failed'}</h3>
      {job.error && (
        <p role="alert" className="error">
          {job.error}
        </p>
      )}
      <p className="counters dim">
        {job.created} created, {job.replaced} replaced, {job.skipped} skipped, {job.invalid} invalid, {job.refused} refused
      </p>
      {job.results && job.results.length > 0 && (
        <table className="result-table" aria-label="Row outcomes">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Title</th>
              <th scope="col">Outcome</th>
              <th scope="col">Reason</th>
            </tr>
          </thead>
          <tbody>
            {job.results.map((r) => (
              <tr key={r.index}>
                <td>{r.index + 1}</td>
                <td>{r.prompt_id ? <Link to={`/p/${r.prompt_id}`}>{r.title}</Link> : r.title}</td>
                <td>
                  <span className={`badge badge-${r.outcome}`}>{r.outcome}</span>
                </td>
                <td>{r.reason ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p>
        <Link to={`/?source=${encodeURIComponent(`import:${job.importer}`)}`}>Show imported prompts in the library</Link>
      </p>
      {firstCreated?.prompt_id && (
        <p>
          <Link to={`/p/${firstCreated.prompt_id}`}>Open the first created prompt</Link>
        </p>
      )}
      <button className="primary" onClick={onAgain}>
        Import another
      </button>
    </section>
  )
}
