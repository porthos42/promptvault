import type { DupAction, PreviewRow } from '../api'

/** The backend refuses request bodies over PV_IMPORT_MAX_PAYLOAD_BYTES (5 MiB). */
export const PAYLOAD_LIMIT = 5 * 1024 * 1024

/**
 * True when a file of `size` bytes would overshoot the payload cap once it is
 * packed into the JSON request. Binary files travel as base64, which inflates
 * by a third (4/3), so their wire size is larger than the file.
 */
export function tooLarge(size: number, binary: boolean): boolean {
  const wire = binary ? Math.ceil((size * 4) / 3) : size
  return wire > PAYLOAD_LIMIT
}

/** btoa that survives large arrays (String.fromCharCode has an argument limit). */
export function encodeBase64(bytes: Uint8Array): string {
  let bin = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(bin)
}

/** The draft fields the tabular mapping can bind to columns (backend: importers.tabular.FIELDS). */
export const MAPPING_FIELDS = [
  'title',
  'body',
  'description',
  'category',
  'tags',
  'difficulty',
  'prompt_type',
  'model_hints',
  'output_format',
  'disclaimer',
  'source_url',
  'license',
] as const

export type MappingNotes = { mapped: Record<string, string>; ignored: string[] }

/**
 * Read the applied column mapping back out of the first preview row's warnings.
 * The backend reports them as "columns mapped: title<-Name, body<-Text" and
 * "columns ignored: colA, colB" — there is no inspect endpoint, so the preview
 * is the only place the wizard learns the headers.
 */
export function parseMappingNotes(warnings: string[]): MappingNotes {
  const mapped: Record<string, string> = {}
  const ignored: string[] = []
  for (const w of warnings) {
    if (w.startsWith('columns mapped: ')) {
      for (const pair of w.slice('columns mapped: '.length).split(', ')) {
        const i = pair.indexOf('<-')
        if (i > 0) mapped[pair.slice(0, i)] = pair.slice(i + 2)
      }
    } else if (w.startsWith('columns ignored: ')) {
      ignored.push(...w.slice('columns ignored: '.length).split(', '))
    }
  }
  return { mapped, ignored }
}

/** The header list the mapping table offers: every column the preview knew about. */
export function knownHeaders(notes: MappingNotes): string[] {
  const set = new Set([...Object.values(notes.mapped), ...notes.ignored])
  return [...set].sort((a, b) => a.localeCompare(b))
}

/**
 * Turn the mapping table's {field: header-or-''} selections into the request's
 * `mapping` object. Empty selections are dropped: the backend's Literal-ish
 * contract rejects empty column names, and "none" means "auto-detect".
 */
export function buildMapping(chosen: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const field of MAPPING_FIELDS) {
    const col = chosen[field]
    if (col) out[field] = col
  }
  return out
}

/** The action that will be applied to a duplicate row (per-row override wins). */
export function rowAction(row: PreviewRow, defaultAction: DupAction, actions: Record<string, DupAction>): DupAction {
  return actions[String(row.index)] ?? defaultAction
}

export type ActionCounts = { create: number; replace: number; skip: number; keepBoth: number; invalid: number }

/** What a commit would actually do: what the Commit button states. */
export function actionSummary(
  rows: PreviewRow[],
  defaultAction: DupAction,
  actions: Record<string, DupAction>,
): ActionCounts {
  const counts: ActionCounts = { create: 0, replace: 0, skip: 0, keepBoth: 0, invalid: 0 }
  for (const row of rows) {
    if (row.status === 'invalid') counts.invalid++
    else if (row.status === 'new') counts.create++
    else {
      const a = rowAction(row, defaultAction, actions)
      if (a === 'replace') counts.replace++
      else if (a === 'keep_both') counts.keepBoth++
      else counts.skip++
    }
  }
  return counts
}

/** Rows whose license still needs a confirmation that the current choices don't cover. */
export function unconfirmedLicenseRows(
  rows: PreviewRow[],
  actions: Record<string, DupAction>,
  defaultAction: DupAction,
  confirmLicense: boolean,
  confirmedRows: Set<number>,
): PreviewRow[] {
  return rows.filter(
    (r) =>
      r.needs_license_confirm &&
      r.status !== 'invalid' &&
      !(r.status === 'duplicate' && rowAction(r, defaultAction, actions) === 'skip') &&
      !confirmLicense &&
      !confirmedRows.has(r.index),
  )
}
