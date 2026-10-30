import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

afterEach(() => vi.unstubAllGlobals())

function mockFetch(ok: boolean) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => ({
      ok,
      status: ok ? 200 : 500,
      statusText: ok ? 'OK' : 'Server Error',
      json: async () => (url.endsWith('/version') ? { version: '9.9.9' } : { status: 'ok' }),
    })),
  )
}

describe('App', () => {
  it('shows the API version when the backend is up', async () => {
    mockFetch(true)
    render(<App />)
    expect(await screen.findByText('API online (v9.9.9)')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Prompt Vault' })).toBeInTheDocument()
  })

  it('shows an error when the backend is down', async () => {
    mockFetch(false)
    render(<App />)
    expect(await screen.findByText(/API unreachable/)).toBeInTheDocument()
  })
})
