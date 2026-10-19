import { useRef, useState } from 'react'
import { errorText, useData } from '../app/context'
import { href } from '../app/router'
import { STATEMENT_SOURCES, type UploadFile, type UploadResult } from '../data/Backend'

const sourceLabel = (key?: string) => STATEMENT_SOURCES.find((s) => s.key === key)?.label ?? key ?? ''

async function read(f: File): Promise<UploadFile> {
  return { name: f.name, data: new Uint8Array(await f.arrayBuffer()) }
}

export function Upload() {
  const { backend, changed } = useData()
  const input = useRef<HTMLInputElement>(null)
  const [picked, setPicked] = useState<UploadFile[]>([])
  const [results, setResults] = useState<UploadResult[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  async function pick(list: FileList | null) {
    if (!list?.length) return
    setPicked(await Promise.all([...list].map(read)))
    setResults([])
    setError(undefined)
  }

  async function run(files: UploadFile[], passwords?: Record<string, string>) {
    setBusy(true)
    setError(undefined)
    try {
      const out = await backend.uploadStatements(files, passwords)
      // Replace earlier results for the same files, keep the order picked.
      setResults((prev) => {
        const byFile = new Map(prev.map((r) => [r.file, r]))
        for (const r of out) byFile.set(r.file, r)
        return picked.map((f) => byFile.get(f.name)).filter((r): r is UploadResult => !!r)
      })
      changed()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const needPw = [...new Set(results.filter((r) => r.status === 'password').map((r) => r.passwordFor!))]
  const newCards = results.reduce((a, r) => a + (r.cardsAdded ?? 0), 0)
  const finished = results.length > 0 && !busy && needPw.length === 0

  return (
    <div className="stack">
      <div className="card">
        <p className="muted">
          Pick statement PDFs from any of your banks or e-wallets. They're read on this device; only the results go to
          your Google Drive. Saved passwords are used automatically.
        </p>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={(e) => {
            pick(e.target.files)
            e.target.value = ''
          }}
        />
        <div className="btn-row">
          <button className="btn" onClick={() => input.current?.click()} disabled={busy}>
            Choose PDFs
          </button>
          <button className="btn primary" onClick={() => run(picked)} disabled={busy || picked.length === 0}>
            {busy ? 'Working…' : `Upload ${picked.length || ''}`.trim()}
          </button>
        </div>
        {picked.length > 0 && results.length === 0 && (
          <ul className="file-list">
            {picked.map((f) => (
              <li key={f.name}>
                <span className="file-name">{f.name}</span>
                <span className="muted small">{Math.max(1, Math.round(f.data.length / 1024))} KB</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && (
        <div className="error-box" role="alert">
          <p>{error}</p>
        </div>
      )}

      {needPw.map((src) => (
        <PasswordPrompt
          key={src}
          source={src}
          wrong={results.some((r) => r.passwordFor === src && r.wrongPassword)}
          files={results.filter((r) => r.passwordFor === src).map((r) => r.file)}
          busy={busy}
          onSubmit={(pw) =>
            run(
              picked.filter((f) => results.some((r) => r.file === f.name && r.passwordFor === src)),
              { [src]: pw },
            )
          }
        />
      ))}

      {results.length > 0 && (
        <ul className="results" aria-live="polite">
          {results.map((r) => (
            <li key={r.file} className={`result ${r.status}`}>
              <span className="result-icon" aria-hidden>
                {r.status === 'ok' ? '✓' : r.status === 'password' ? '🔒' : '!'}
              </span>
              <div>
                <div className="file-name">{r.file}</div>
                {r.source && <div className="muted small">{sourceLabel(r.source)}</div>}
                <div className="small">{r.message}</div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {finished && (
        <div className="btn-row">
          {newCards > 0 ? (
            <a className="btn primary" href={href({ name: 'cards' })}>
              Go through {newCards} new {newCards === 1 ? 'card' : 'cards'}
            </a>
          ) : (
            <a className="btn" href={href({ name: 'home' })}>
              Done
            </a>
          )}
        </div>
      )}
    </div>
  )
}

function PasswordPrompt({
  source,
  wrong,
  files,
  busy,
  onSubmit,
}: {
  source: string
  wrong: boolean
  files: string[]
  busy: boolean
  onSubmit(pw: string): void
}) {
  const [pw, setPw] = useState('')
  const [show, setShow] = useState(false)
  return (
    <form
      className="card pw-prompt"
      onSubmit={(e) => {
        e.preventDefault()
        if (pw) onSubmit(pw)
        setPw('')
      }}
    >
      <h3>{sourceLabel(source)} password</h3>
      <p className="small">
        {wrong ? "That password didn't open " : 'No password saved yet for '}
        {files.join(', ')}. It's saved to your Drive's private app folder once it works.
      </p>
      <div className="pw-row">
        <input
          type={show ? 'text' : 'password'}
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          autoComplete="off"
          aria-label={`${sourceLabel(source)} PDF password`}
          placeholder="PDF password"
        />
        <button type="button" className="btn ghost" onClick={() => setShow((s) => !s)}>
          {show ? 'Hide' : 'Show'}
        </button>
      </div>
      <button className="btn primary" disabled={busy || !pw}>
        Open
      </button>
    </form>
  )
}
