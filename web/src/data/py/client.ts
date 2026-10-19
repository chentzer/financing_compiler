/** Calls into webapi.py running in the Pyodide worker. */

let worker: Worker | null = null
let nextId = 1
const waiting = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>()

function get(): Worker {
  if (worker) return worker
  worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })
  worker.onmessage = (e: MessageEvent) => {
    const { id, result, error } = e.data
    const w = waiting.get(id)
    waiting.delete(id)
    if (!w) return
    if (error) w.reject(new Error(error))
    else w.resolve(result)
  }
  return worker
}

// Dev builds only: lets the browser console call webapi.py directly.
if (import.meta.env.DEV) (window as unknown as { __fincompPy: typeof py }).__fincompPy = py

/** Start loading Python early (first load downloads ~10 MB, then it's cached). */
export function warmUp(): void {
  void py('settings_template', [])
}

export function py<T = unknown>(fn: string, args: unknown[], files?: { name: string; data: Uint8Array }[]): Promise<T> {
  const id = nextId++
  return new Promise<T>((resolve, reject) => {
    waiting.set(id, { resolve: resolve as (v: unknown) => void, reject })
    // public/py/fincomp.json, relative to the page (works on Pages and in the app).
    const bundleUrl = new URL('py/fincomp.json', document.baseURI).href
    get().postMessage({ id, fn, args, files, bundleUrl })
  })
}
