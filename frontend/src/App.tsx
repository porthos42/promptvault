import { useEffect, useState } from 'react'
import { api } from './api'

type Status = { state: 'loading' } | { state: 'ok'; version: string } | { state: 'down'; error: string }

export default function App() {
  const [status, setStatus] = useState<Status>({ state: 'loading' })

  useEffect(() => {
    let cancelled = false
    Promise.all([api.health(), api.version()])
      .then(([, v]) => !cancelled && setStatus({ state: 'ok', version: v.version }))
      .catch((e: unknown) =>
        !cancelled && setStatus({ state: 'down', error: e instanceof Error ? e.message : String(e) }),
      )
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main className="app">
      <header>
        <h1>Prompt Vault</h1>
        <p className="tagline">Your searchable prompt engineering library.</p>
      </header>
      <section aria-live="polite" className="status" data-state={status.state}>
        {status.state === 'loading' && 'Connecting to API...'}
        {status.state === 'ok' && `API online (v${status.version})`}
        {status.state === 'down' && `API unreachable: ${status.error}`}
      </section>
    </main>
  )
}
