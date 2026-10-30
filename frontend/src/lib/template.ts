import type { Variable } from '../api'

// Mirrors backend services/variables.py so the preview updates without a round trip.
const VAR_RE = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g

export function renderTemplate(
  body: string,
  variables: Variable[],
  values: Record<string, string>,
): { text: string; missing: string[] } {
  const defaults = Object.fromEntries(variables.map((v) => [v.name, v.default]))
  const missing: string[] = []
  const text = body.replace(VAR_RE, (whole, name: string) => {
    const val = values[name] || defaults[name]
    if (!val) {
      if (!missing.includes(name)) missing.push(name)
      return whole
    }
    return val
  })
  return { text, missing }
}
