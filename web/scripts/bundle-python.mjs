// Copies the fincomp Python package (../src/fincomp) into public/py/fincomp.json
// as {relative path: source}, which the Pyodide worker writes into its file
// system. Runs before `vite` and `vite build` (see package.json), so the app
// always ships the same Python the tests ran against.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const src = path.resolve(here, '../../src/fincomp')
const out = path.resolve(here, '../public/py/fincomp.json')

// CLI-only modules the browser never imports (they'd pull in pandas, gspread...).
const SKIP = new Set(['cli.py', '__main__.py', 'gsheets.py', 'accounts_xlsx.py', 'export.py', 'review.py'])

const files = {}
function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === '__pycache__') continue
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full)
    else if (e.name.endsWith('.py') && !SKIP.has(e.name)) {
      files[path.relative(src, full).split(path.sep).join('/')] = fs.readFileSync(full, 'utf8')
    }
  }
}
walk(src)
fs.mkdirSync(path.dirname(out), { recursive: true })
fs.writeFileSync(out, JSON.stringify(files))
console.log(`bundled ${Object.keys(files).length} Python files into public/py/fincomp.json`)
