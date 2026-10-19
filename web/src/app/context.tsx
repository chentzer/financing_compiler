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

/** Runs `fn` against the backend and reruns it when `deps` or the data version change. */
export function useLoad<T>(fn: (b: Backend) => Promise<T>, deps: unknown[] = []): Load<T> {
  const { backend, version } = useData()
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let live = true
    setState((s) => ({ ...s, loading: true, error: undefined }))
    fn(backend).then(
      (data) => live && setState({ data, loading: false }),
      (e) => live && setState({ error: errorText(e), loading: false }),
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
