import { ApiError } from '../api'

/** The importers that fetch a URL from the server (backend: importers/net.py users). */
export const NETWORK_IMPORTERS = ['github', 'huggingface', 'url'] as const
export type NetworkImporter = (typeof NETWORK_IMPORTERS)[number]

export function isNetworkImporter(name: string): boolean {
  return (NETWORK_IMPORTERS as readonly string[]).includes(name)
}

const HAS_SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i
/** A bare Hugging Face dataset id: org/name with no scheme and no dot before the slash. */
const BARE_ID = /^[^\s/.]+\/[^\s/]+$/

/**
 * Detect which importer a pasted address belongs to: github.com -> github,
 * huggingface.co (or hf.co, or a bare org/name dataset id) -> huggingface,
 * any other parseable address -> url. Junk input answers null.
 */
export function detectImporter(raw: string): NetworkImporter | null {
  const text = raw.trim()
  if (!text || /\s/.test(text)) return null
  if (BARE_ID.test(text)) return 'huggingface'
  const candidate = HAS_SCHEME.test(text) ? text : `https://${text}`
  let host: string
  try {
    host = new URL(candidate).hostname.toLowerCase()
  } catch {
    return null
  }
  if (host === 'github.com' || host.endsWith('.github.com')) return 'github'
  if (host === 'huggingface.co' || host === 'hf.co') return 'huggingface'
  return 'url'
}

/** Options the source step can collect per importer. */
export type UrlOptions = { config: string; split: string; limit: string; mode: 'page' | 'blocks' }

export const EMPTY_URL_OPTIONS: UrlOptions = { config: '', split: '', limit: '', mode: 'page' }

/**
 * The request's `source` object for a network importer. Empty option values are
 * dropped: the backend's Literal/typed fields reject empty strings, and their
 * absence means "auto-detect" server-side.
 */
export function buildNetworkSource(imp: NetworkImporter, url: string, o: UrlOptions): Record<string, unknown> {
  const out: Record<string, unknown> = { url: url.trim() }
  if (imp === 'huggingface') {
    if (o.config.trim()) out.config = o.config.trim()
    if (o.split.trim()) out.split = o.split.trim()
    const lim = o.limit.trim()
    if (/^\d+$/.test(lim) && Number(lim) > 0) out.limit = Number(lim)
  } else if (imp === 'url') {
    out.mode = o.mode
  }
  return out
}

/** Drop any query string a message may echo, and trim surrounding noise. */
export function stripQuery(text: string): string {
  return text.replace(/https?:\/\/\S+/g, (m) => m.split(/[?#]/)[0])
}

/**
 * Plain-language text for the failures the network importers produce, with a
 * short hint. Never echoes a query string back to the user.
 */
export function networkErrorText(e: unknown): string {
  const fallback = 'The import request failed. Check the address and retry.'
  if (!(e instanceof ApiError)) return e instanceof Error ? stripQuery(e.message) || fallback : fallback
  const detail = stripQuery(e.message)
  if (e.status === 422) {
    if (/private|non-public|not public|loopback|metadata|reserved|port\b/i.test(detail)) {
      return (
        'The server refused this address: imports only reach public hosts on ports 80 and 443. ' +
        'To allow a host on your own network, list it in the server setting PV_IMPORT_ALLOW_PRIVATE_HOSTS.'
      )
    }
    return (
      `This URL was refused by the importer: ${detail}. ` +
      'Network imports read public pages only — no gated datasets, no JavaScript-rendered pages, no crawling.'
    )
  }
  if (e.status === 502) {
    if (/rate|limit|60|hour/i.test(detail)) {
      return (
        'The remote service refused the request: GitHub allows 60 anonymous requests per hour. ' +
        'Set PV_GITHUB_TOKEN on the server to raise the limit, then retry.'
      )
    }
    return `The remote service failed to answer: ${detail || 'unknown error'}. This is usually temporary — retry in a moment.`
  }
  if (e.status === 504 || /timed?\s?out/i.test(detail)) {
    return 'The remote service took too long to answer. Check the address and retry.'
  }
  return detail || fallback
}

export type FetchedNotes = { skipped: string[]; truncated: string[]; other: string[] }

/**
 * Build the "What was fetched" block from the importer's row-1 warnings:
 * skipped files, truncation and any other remote note. The column-mapping
 * notes are excluded (the mapping step owns them).
 */
export function parseFetchedNotes(warnings: string[]): FetchedNotes {
  const notes: FetchedNotes = { skipped: [], truncated: [], other: [] }
  for (const w of warnings) {
    if (w.startsWith('columns mapped: ') || w.startsWith('columns ignored: ')) continue
    if (/skip/i.test(w)) notes.skipped.push(w)
    else if (/truncat/i.test(w)) notes.truncated.push(w)
    else notes.other.push(w)
  }
  return notes
}

export function hasFetchedNotes(n: FetchedNotes): boolean {
  return n.skipped.length + n.truncated.length + n.other.length > 0
}

/** What each network importer can and cannot read (shown on the source step). */
export const IMPORTER_NOTES: Record<NetworkImporter, { can: string; cannot: string }> = {
  github: {
    can: 'Reads the .md, .json, .yaml and .csv files of a public repository (optionally one folder or file via /tree/branch/path) or a gist, and labels rows with the repository license.',
    cannot: 'No JavaScript-rendered content, no crawling beyond the URL you give, and large repositories stop at the server file limit.',
  },
  huggingface: {
    can: 'Reads rows of a public dataset through the datasets-server API; config, split and a row limit can be chosen below.',
    cannot: 'No gated or private datasets (the server has no token), and parquet-only datasets are not supported yet.',
  },
  url: {
    can: 'Reads one public page or file by URL: HTML blocks, Markdown, plain text, JSON, YAML or CSV (mode page or blocks).',
    cannot: 'No JavaScript-rendered pages and no crawling; a page license counts only when the page itself states one.',
  },
}

export const SSRF_SENTENCE =
  'These imports are fetched by the server, which only reaches public hosts on ports 80 and 443 — private and local addresses are refused.'
export const PRIVATE_HOST_HINT =
  'To import from a host on your own network, list it in the server setting PV_IMPORT_ALLOW_PRIVATE_HOSTS.'

export const URL_PLACEHOLDER: Record<NetworkImporter, string> = {
  github: 'https://github.com/owner/repo (or /tree/branch/path, a blob URL, or a gist)',
  huggingface: 'huggingface.co/datasets/org/name (or a bare dataset id like org/name)',
  url: 'https://example.com/page-to-read',
}