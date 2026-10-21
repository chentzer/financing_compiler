import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import type { Backend } from '../data/Backend'

interface DataContext {
  backend: Backend
  /** Bumped after every change, so loaded screens refetch. */
  version: number
  changed(): void
  toast(message: string): void
}

const Ctx = createContext<DataContext | null>(null)

export function DataProvider({ backend, children }: { backend: Backend; children: ReactNode }) {
  const [version, setVersion] = useState(0)
  const [message, setMessage] = useState<string | null>(null)
  const changed = useCallback(() => setVersion((v) => v + 1), [])
  const toast = useCallback((m: string) => setMessage(m), [])

  useEffect(() => {
    if (!message) return
    const t = setTimeout(() => setMessage(null), 2600)
    return () => clearTimeout(t)
  }, [message])

  return (
    <Ctx.Provider value={{ backend, version, changed, toast }}>
      {children}
      {message && (
        <div className="toast" role="status">
          {message}
        </div>
      )}
    </Ctx.Provider>
  )
}

export function useData(): DataContext {
  const c = useContext(Ctx)
  if (!c) throw new Error('useData outside DataProvider')
  return c
}

export type Load<T> = { data?: T; error?: string; loading: boolean; reload(): void }

/** What each screen last loaded (per signed-in backend), shown at once when you come back while it refreshes. */
const loadedBy = new WeakMap<Backend, Map<string, unknown>>()
function cacheOf(b: Backend): Map<string, unknown> {
  let m = loadedBy.get(b)
  if (!m) loadedBy.set(b, (m = new Map()))
  return m
}

/** Runs `fn` against the backend and reruns it when `deps` or the data version change. */
export function useLoad<T>(fn: (b: Backend) => Promise<T>, deps: unknown[] = []): Load<T> {
  const { backend, version } = useData()
  const key = fn.toString() + JSON.stringify(deps)
  const lastLoaded = cacheOf(backend)
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>(() => ({
    data: lastLoaded.get(key) as T | undefined,
    loading: true,
  }))
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let live = true
    // Never the previous month's data for this one: only what this exact load showed before.
    setState({ data: lastLoaded.get(key) as T | undefined, loading: true, error: undefined })
    fn(backend).then(
      (data) => {
        lastLoaded.set(key, data)
        if (live) setState({ data, loading: false })
      },
      (e) => live && setState((s) => ({ data: s.data, error: errorText(e), loading: false })),
    )
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backend, version, tick, ...deps])

  return { ...state, reload: () => setTick((t) => t + 1) }
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
