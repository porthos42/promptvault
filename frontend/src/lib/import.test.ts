import { describe, expect, it } from 'vitest'
import type { PreviewRow } from '../api'
import {
  PAYLOAD_LIMIT,
  actionSummary,
  buildMapping,
  knownHeaders,
  parseMappingNotes,
  rowAction,
  tooLarge,
  unconfirmedLicenseRows,
} from './import'

function row(partial: Partial<PreviewRow> & { index: number }): PreviewRow {
  return {
    status: 'new',
    errors: [],
    warnings: [],
    needs_license_confirm: false,
    draft: {
      title: 'T',
      body: 'B',
      description: '',
      category: null,
      tags: [],
      difficulty: null,
      prompt_type: null,
      model_hints: null,
      output_format: null,
      disclaimer: null,
      source_url: null,
      license: null,
      variables: [],
    },
    match: null,
    ...partial,
  }
}

describe('tooLarge', () => {
  it('passes text at the cap and binary below it', () => {
    expect(tooLarge(PAYLOAD_LIMIT, false)).toBe(false)
    expect(tooLarge(PAYLOAD_LIMIT + 1, false)).toBe(true)
    const maxBinary = Math.floor((PAYLOAD_LIMIT * 3) / 4)
    expect(tooLarge(maxBinary, true)).toBe(false)
    expect(tooLarge(maxBinary + 1, true)).toBe(true)
  })
})

describe('parseMappingNotes', () => {
  it('reads the applied mapping and ignored columns from row-1 warnings', () => {
    const notes = parseMappingNotes([
      'columns mapped: title<-Name, body<-Text, tags<-Labels',
      'columns ignored: extra, spare',
    ])
    expect(notes.mapped).toEqual({ title: 'Name', body: 'Text', tags: 'Labels' })
    expect(notes.ignored).toEqual(['extra', 'spare'])
    expect(knownHeaders(notes)).toEqual(['extra', 'Labels', 'Name', 'spare', 'Text'])
  })

  it('tolerates unrelated warnings and empty input', () => {
    expect(parseMappingNotes([])).toEqual({ mapped: {}, ignored: [] })
    expect(parseMappingNotes(['row 3: title is empty'])).toEqual({ mapped: {}, ignored: [] })
  })
})

describe('buildMapping', () => {
  it('drops empty selections so the backend gets only real columns', () => {
    expect(buildMapping({ title: 'Name', body: '', tags: undefined as never })).toEqual({ title: 'Name' })
    expect(buildMapping({})).toEqual({})
  })
})

describe('actionSummary', () => {
  const rows = [row({ index: 0 }), row({ index: 1, status: 'duplicate' }), row({ index: 2, status: 'invalid' })]

  it('counts by the default action', () => {
    expect(actionSummary(rows, 'skip', {})).toEqual({ create: 1, replace: 0, skip: 1, keepBoth: 0, invalid: 1 })
    expect(actionSummary(rows, 'replace', {})).toEqual({ create: 1, replace: 1, skip: 0, keepBoth: 0, invalid: 1 })
  })

  it('applies the per-row override', () => {
    expect(actionSummary(rows, 'skip', { '1': 'keep_both' })).toEqual({
      create: 1,
      replace: 0,
      skip: 0,
      keepBoth: 1,
      invalid: 1,
    })
  })

  it('rowAction prefers the override keyed by row index', () => {
    expect(rowAction(rows[1], 'skip', { '1': 'replace' })).toBe('replace')
    expect(rowAction(rows[1], 'skip', {})).toBe('skip')
  })
})

describe('unconfirmedLicenseRows', () => {
  const licensed = row({ index: 5, needs_license_confirm: true })
  const skippedDup = row({
    index: 6,
    status: 'duplicate',
    needs_license_confirm: true,
    match: { kind: 'exact', score: 1, title: 'x', prompt_id: 'p', batch_index: null },
  })

  it('lists rows the current choices do not cover', () => {
    expect(unconfirmedLicenseRows([licensed], {}, 'skip', false, new Set())).toEqual([licensed])
    expect(unconfirmedLicenseRows([licensed], {}, 'skip', true, new Set())).toEqual([])
    expect(unconfirmedLicenseRows([licensed], {}, 'skip', false, new Set([5]))).toEqual([])
  })

  it('ignores duplicates that will be skipped anyway', () => {
    expect(unconfirmedLicenseRows([skippedDup], {}, 'skip', false, new Set())).toEqual([])
    expect(unconfirmedLicenseRows([skippedDup], { '6': 'replace' }, 'skip', false, new Set())).toEqual([skippedDup])
  })
})
