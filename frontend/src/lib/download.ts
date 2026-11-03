/** Download plumbing shared by the export panel and the per-prompt actions. */

/** Save a Blob the way the browser's download manager expects. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** `attachment; filename="x.json"` -> `x.json` */
export function filenameFromDisposition(cd: string | null): string | null {
  const m = cd?.match(/filename="?([^";]+)"?/)
  return m ? m[1] : null
}
