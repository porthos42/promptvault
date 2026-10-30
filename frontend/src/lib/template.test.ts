import { describe, expect, it } from 'vitest'
import { renderTemplate } from './template'

const vars = [
  { name: 'role', label: 'Role', type: 'text' as const, default: 'analyst', options: [] },
  { name: 'topic', label: 'Topic', type: 'text' as const, default: '', options: [] },
]

describe('renderTemplate', () => {
  it('substitutes values, falls back to defaults, reports missing', () => {
    const r = renderTemplate('As {{ role }}, explain {{topic}} to {{audience}}.', vars, { topic: 'FTS5' })
    expect(r.text).toBe('As analyst, explain FTS5 to {{audience}}.')
    expect(r.missing).toEqual(['audience'])
  })

  it('treats empty values as unset', () => {
    expect(renderTemplate('{{role}}', vars, { role: '' }).text).toBe('analyst')
  })

  it('substitutes repeated placeholders', () => {
    expect(renderTemplate('{{topic}} {{topic}}', vars, { topic: 'x' }).text).toBe('x x')
  })
})
