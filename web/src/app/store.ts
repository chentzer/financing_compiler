import { useCallback, useSyncExternalStore } from 'react'

/**
 * State that outlives a screen: like useState, but kept while you go to
 * another tab and back (e.g. an upload that's still running). Lost on reload.
 */
const values = new Map<string, unknown>()
const listeners = new Set<() => void>()

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

export function useStored<T>(key: string, initial: T): [T, (next: T | ((prev: T) => T)) => void] {
  if (!values.has(key)) values.set(key, initial)
  const value = useSyncExternalStore(subscribe, () => values.get(key) as T)
  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      const prev = values.get(key) as T
      values.set(key, typeof next === 'function' ? (next as (p: T) => T)(prev) : next)
      listeners.forEach((l) => l())
    },
    [key],
  )
  return [value, set]
}
