import { describe, expect, it } from 'vitest'
import { ApiError } from '../api'
import {
  IMPORTER_NOTES,
  SSRF_SENTENCE,
  buildNetworkSource,
  detectImporter,
  hasFetchedNotes,
  networkErrorText,
  parseFetchedNotes,
  stripQuery,
} from './urlsource'

describe('detectImporter', () => {
  it.each([
    ['https://github.com/o/r', 'github'],
    ['github.com/o/r', 'github'],
    ['https://github.com/o/r/tree/main/prompts', 'github'],
    ['https://github.com/o/r/blob/main/prompts.md', 'github'],
    ['https://gist.github.com/user/abc123', 'github'],
    ['https://huggingface.co/datasets/fka/prompts.chat', 'huggingface'],
    ['https://huggingface.co/datasets/o/n/viewer/default', 'huggingface'],
    ['fka/prompts.chat', 'huggingface'],
    ['https://example.com/page', 'url'],
    ['example.com', 'url'],
    ['http://example.com:8080/x', 'url'],
  ])('%s -> %s', (input, expected) => {
    expect(detectImporter(input)).toBe(expected)
  })

  it.each([
    [''],
    ['   '],
    ['not a url at all'],
    ['two words here'],
    ['git lab . com/x'],
  ])('%s -> null (junk)', (input) => {
    expect(detectImporter(input)).toBeNull()
  })
})

describe('buildNetworkSource', () => {
  it('github sends just the url', () => {
    expect(buildNetworkSource('github', ' https://github.com/o/r ', { config: '', split: '', limit: '', mode: 'page' })).toEqual({
      url: 'https://github.com/o/r',
    })
  })

  it('huggingface trims and drops empty values, sends limit as a number', () => {
    expect(
      buildNetworkSource('huggingface', 'fka/prompts.chat', { config: ' train ', split: '', limit: '25', mode: 'page' }),
    ).toEqual({ url: 'fka/prompts.chat', config: 'train', limit: 25 })
  })

  it('huggingface ignores a junk limit instead of sending it', () => {
    const src = buildNetworkSource('huggingface', 'o/n', { config: '', split: '', limit: 'abc', mode: 'page' })
    expect(Object.keys(src)).toEqual(['url'])
  })

  it('url sends the chosen mode', () => {
    expect(buildNetworkSource('url', 'https://example.com', { config: '', split: '', limit: '', mode: 'blocks' })).toEqual({
      url: 'https://example.com',
      mode: 'blocks',
    })
  })
})

describe('networkErrorText', () => {
  it('maps a private-host 422 to the server setting hint', () => {
    const text = networkErrorText(new ApiError(422, 'refused: address is not public'))
    expect(text).toContain('public hosts on ports 80 and 443')
    expect(text).toContain('PV_IMPORT_ALLOW_PRIVATE_HOSTS')
  })

  it('maps a generic 422 to what the importers cannot do', () => {
    const text = networkErrorText(new ApiError(422, 'bad source'))
    expect(text).toContain('refused by the importer')
    expect(text).toContain('gated datasets')
  })

  it('maps a rate-limit 502 to the GitHub hint', () => {
    const text = networkErrorText(new ApiError(502, 'remote returned 403: API rate limit exceeded'))
    expect(text).toContain('60 anonymous requests per hour')
    expect(text).toContain('PV_GITHUB_TOKEN')
  })

  it('maps a plain 502 to a retry hint', () => {
    const text = networkErrorText(new ApiError(502, 'upstream connect error'))
    expect(text).toContain('usually temporary')
  })

  it('maps a 504 to a timeout message', () => {
    expect(networkErrorText(new ApiError(504, 'gateway timed out'))).toContain('took too long')
  })

  it('strips query strings from any echoed URL', () => {
    const leaked = 'refused: https://example.com/page?token=SECRET&x=1 is not allowed'
    expect(stripQuery(leaked)).not.toContain('token=SECRET')
    expect(networkErrorText(new ApiError(422, leaked))).not.toContain('SECRET')
  })
})

describe('parseFetchedNotes', () => {
  it('sorts warnings into skipped, truncated and other, excluding column notes', () => {
    const notes = parseFetchedNotes([
      'columns mapped: title<-Name',
      'columns ignored: extra',
      'skipped: README.md, LICENSE',
      'truncated the file list at 50 files',
      'repo license: NOASSERTION',
    ])
    expect(notes.skipped).toEqual(['skipped: README.md, LICENSE'])
    expect(notes.truncated).toEqual(['truncated the file list at 50 files'])
    expect(notes.other).toEqual(['repo license: NOASSERTION'])
    expect(hasFetchedNotes(notes)).toBe(true)
  })

  it('answers empty for plain tabular imports', () => {
    const notes = parseFetchedNotes(['columns mapped: title<-Name'])
    expect(hasFetchedNotes(notes)).toBe(false)
  })
})

describe('copy', () => {
  it('every importer documents what it can and cannot do, plus the SSRF sentence', () => {
    for (const imp of ['github', 'huggingface', 'url'] as const) {
      expect(IMPORTER_NOTES[imp].can.length).toBeGreaterThan(20)
      expect(IMPORTER_NOTES[imp].cannot).toMatch(/no /i)
    }
    expect(SSRF_SENTENCE).toContain('public hosts')
  })
})