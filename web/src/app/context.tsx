import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import type { Backend } from '../data/Backend'

interface DataContext {
  backend: Backend
  /** Bumped after every change, so loaded screens refetch. */
  version: number
  changed(): void
  toast(message: string): void
  /**
   * Do something that can be taken back: the screen already shows it done, `run` writes it
   * to Google after a few seconds unless Undo on the toast is tapped (then `undo` puts the
   * screen back). Leaving the page writes it at once.
   */
  later(message: string, run: () => Promise<void>, undo: () => void): void
}

const UNDO_MS = 5000

const Ctx = createContext<DataContext | null>(null)

export function DataProvider({ backend, children }: { backend: Backend; children: ReactNode }) {
  const [version, setVersion] = useState(0)
  const [message, setMessage] = useState<{ text: string; undo?: () => void } | null>(null)
  const changed = useCallback(() => setVersion((v) => v + 1), [])
  const toast = useCallback((m: string) => setMessage({ text: m }), [])

  // Waiting writes, in order. They run one at a time.
  const waiting = useRef(new Map<number, { run: () => Promise<void>; timer: number }>())
  const chain = useRef<Promise<unknown>>(Promise.resolve())
  const nextId = useRef(0)

  const start = useCallback((id: number) => {
    const w = waiting.current.get(id)
    if (!w) return
    waiting.current.delete(id)
    clearTimeout(w.timer)
    chain.current = chain.current
      .then(w.run)
      .catch((e) => setMessage({ text: `Couldn't save: ${errorText(e)}` }))
      .finally(() => {
        if (!waiting.current.size) changed()
      })
  }, [changed])

  const later = useCallback((text: string, run: () => Promise<void>, undo: () => void) => {
    const id = nextId.current++
    const timer = window.setTimeout(() => start(id), UNDO_MS)
    waiting.current.set(id, { run, timer })
    setMessage({
      text,
      undo: () => {
        const w = waiting.current.get(id)
        if (!w) return
        clearTimeout(w.timer)
        waiting.current.delete(id)
        undo()
        setMessage({ text: 'Undone' })
      },
    })
  }, [start])

  // Closing or hiding the app: write what's waiting now rather than lose it.
  useEffect(() => {
    const flush = () => {
      if (document.visibilityState === 'hidden') [...waiting.current.keys()].forEach(start)
    }
    document.addEventListener('visibilitychange', flush)
    return () => document.removeEventListener('visibilitychange', flush)
  }, [start])

  useEffect(() => {
    if (!message) return
    const t = setTimeout(() => setMessage(null), message.undo ? UNDO_MS : 2600)
    return () => clearTimeout(t)
  }, [message])

  return (
    <Ctx.Provider value={{ backend, version, changed, toast, later }}>
      {children}
      {message && (
        <div className="toast" role="status">
          <span>{message.text}</span>
          {message.undo && (
            <button type="button" className="undo" onClick={message.undo}>
              Undo
            </button>
          )}
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
