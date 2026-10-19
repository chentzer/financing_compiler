/// <reference lib="webworker" />
/**
 * Runs the fincomp Python package (webapi.py) in Pyodide, off the main
 * thread so the page stays responsive while PDFs are parsed.
 *
 * Messages in:  { id, fn, args, files?, bundleUrl }  (files: [{name, data: Uint8Array}])
 * Messages out: { id, result } or { id, error }
 * Arguments and results are JSON; file bytes go through Pyodide's FS.
 */

const PYODIDE_VERSION = '0.26.4'
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`
const PYPDF = 'pypdf==6.21.1'  // same version the Python tests run on

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Pyodide = any

let ready: Promise<Pyodide> | null = null

async function boot(bundleUrl: string): Promise<Pyodide> {
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)
  const py: Pyodide = await loadPyodide({ indexURL: PYODIDE_URL })
  // cryptography opens AES-encrypted statements; pypdf reads them.
  await py.loadPackage(['micropip', 'cryptography'])
  await py.runPythonAsync(`import micropip\nawait micropip.install("${PYPDF}")`)

  const bundle: Record<string, string> = await (await fetch(bundleUrl)).json()
  for (const [rel, text] of Object.entries(bundle)) {
    const full = `/home/pyodide/fincomp/${rel}`
    py.FS.mkdirTree(full.slice(0, full.lastIndexOf('/')))
    py.FS.writeFile(full, text)
  }
  py.FS.mkdirTree('/tmp/upload')
  await py.runPythonAsync(`
import json, os, sys
sys.path.insert(0, "/home/pyodide")
from fincomp import webapi

def _call(fn, args_json, file_names):
    args = json.loads(args_json)
    if file_names is not None:
        names = list(file_names)
        args[0] = [{"name": n, "data": open("/tmp/upload/" + str(i), "rb").read()} for i, n in enumerate(names)]
    return json.dumps(getattr(webapi, fn)(*args), default=str)
`)
  return py
}

self.onmessage = async (e: MessageEvent) => {
  const { id, fn, args, files, bundleUrl } = e.data as {
    id: number
    fn: string
    args: unknown[]
    files?: { name: string; data: Uint8Array }[]
    bundleUrl: string
  }
  try {
    ready ??= boot(bundleUrl)
    const py = await ready
    let names: string[] | null = null
    if (files) {
      for (const f of py.FS.readdir('/tmp/upload')) if (f !== '.' && f !== '..') py.FS.unlink(`/tmp/upload/${f}`)
      files.forEach((f, i) => py.FS.writeFile(`/tmp/upload/${i}`, f.data))
      names = files.map((f) => f.name)
    }
    const call = py.globals.get('_call')
    const out: string = call(fn, JSON.stringify(args), names ? py.toPy(names) : null)
    call.destroy()
    self.postMessage({ id, result: JSON.parse(out) })
  } catch (err) {
    self.postMessage({ id, error: err instanceof Error ? err.message : String(err) })
  }
}
