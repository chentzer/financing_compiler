import { useEffect, useRef, useState } from 'react'
import { useStored } from '../app/store'
import { backgroundProgress, backgroundStart, backgroundStop, canRunInBackground } from '../app/background'
import { errorText, useData, useLoad } from '../app/context'
import { monthName } from '../app/format'
import { href } from '../app/router'
import { PinGate } from '../components/PinGate'
import { STATEMENT_SOURCES, type UploadFile, type UploadProgress, type UploadResult } from '../data/Backend'

const sourceLabel = (key?: string) => STATEMENT_SOURCES.find((s) => s.key === key)?.label ?? ({ splitwise: 'Splitwise', workbook: 'Accounts workbook' } as Record<string, string>)[key ?? ''] ?? key ?? ''

async function read(f: File): Promise<UploadFile> {
  return { name: f.name, data: new Uint8Array(await f.arrayBuffer()) }
}

export function Upload() {
  return (
    <PinGate reason="Statements from TNG, AEON Credit and others are locked with a password.">
      <UploadInner />
    </PinGate>
  )
}

function UploadInner() {
  const { backend, changed } = useData()
  const input = useRef<HTMLInputElement>(null)
  // Kept while you look at another tab; an upload keeps running meanwhile.
  const [picked, setPicked] = useStored<UploadFile[]>('upload.picked', [])
  const [results, setResults] = useStored<UploadResult[]>('upload.results', [])
  const [busy, setBusy] = useStored('upload.busy', false)
  const [error, setError] = useStored<string | undefined>('upload.error', undefined)
  const [progress, setProgress] = useStored<UploadProgress | undefined>('upload.progress', undefined)
  // Files shared to FinMerge from another app upload by themselves (app/share.ts).
  const [auto, setAuto] = useStored('upload.auto', false)
  const [dragging, setDragging] = useState(false)
  const keep = useLoad((b) => b.getKeepPdfCopies())

  /** Each pick adds to the list (statements often sit in different folders);
   * picking the same file again replaces it. */
  async function pick(list: FileList | null) {
    // Statement PDFs, Splitwise exports (CSV), and accounts workbooks you kept by hand (XLSX).
    const pdfs = [...(list ?? [])].filter((f) => f.type === 'application/pdf' || /\.(pdf|csv|xlsx)$/i.test(f.name))
    if (!pdfs.length) return
    const added = await Promise.all(pdfs.map(read))
    setPicked((prev) => [...prev.filter((p) => !added.some((a) => a.name === p.name)), ...added])
    setResults([])
    setError(undefined)
  }

  function remove(name: string) {
    setPicked((prev) => prev.filter((f) => f.name !== name))
  }

  async function run(files: UploadFile[], passwords?: Record<string, string>) {
    setBusy(true)
    setError(undefined)
    setProgress({ fraction: 0, step: 'Starting' })
    // Android: keeps going if you switch apps or the screen goes off (progress notification).
    await backgroundStart(files.length === 1 ? files[0].name : `${files.length} files`)
    let done: string | undefined
    try {
      const out = await backend.uploadStatements(files, passwords, (p) => {
        setProgress(p)
        backgroundProgress(p)
      })
      const ok = out.filter((r) => r.status === 'ok').length
      const cards = out.reduce((a, r) => a + (r.cardsAdded ?? 0), 0)
      done = `${ok} of ${out.length} ${out.length === 1 ? 'file' : 'files'} uploaded${cards ? ` · ${cards} to update` : ''}`
      // Replace earlier results for the same files, keep the order picked.
      setResults((prev) => {
        const byFile = new Map(prev.map((r) => [r.file, r]))
        for (const r of out) byFile.set(r.file, r)
        return picked.map((f) => byFile.get(f.name)).filter((r): r is UploadResult => !!r)
      })
      changed()
    } catch (e) {
      setError(errorText(e))
      done = `Upload stopped: ${errorText(e)}`
    } finally {
      setBusy(false)
      setProgress(undefined)
      await backgroundStop(done)
    }
  }

  useEffect(() => {
    if (!auto || busy || !picked.length) return
    setAuto(false)
    void run(picked)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, busy, picked])

  const needPw = [...new Set(results.filter((r) => r.status === 'password').map((r) => r.passwordFor!))]
  const newCards = results.reduce((a, r) => a + (r.cardsAdded ?? 0), 0)
  const finished = results.length > 0 && !busy && needPw.length === 0

  return (
    <div className="stack">
      <Checklist />
      <div
        className={`card${dragging ? ' drop-target' : ''}`}
        data-tour="upload-pick"
        onDragOver={(e) => {
          e.preventDefault()
          if (!busy) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          if (!busy) pick(e.dataTransfer.files)
        }}
      >
        <p className="muted">
          Pick statement PDFs from any of your banks or e-wallets, or a Splitwise export (CSV): several at once,
          or a few at a time from different folders (or drop them here). They're read on this device; only the
          results go to your Google Drive. Saved passwords are used automatically. For Splitwise, what you paid is
          spending and money paid back to you is earnings, at your trip's rate (set in Trips). An accounts
          workbook you kept yourself (.xlsx, like "2022 Accounts") has its month tabs copied in as they are.
        </p>
        {keep.data !== undefined && (
          <p className="muted small">
            {keep.data ? 'A copy of each PDF is kept in Drive › fincomp › statements.' : 'PDFs are discarded after reading.'}{' '}
            <a href={href({ name: 'settings', tab: 'uploads' })}>Change in Settings</a>
          </p>
        )}
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf,text/csv,.csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          multiple
          hidden
          onChange={(e) => {
            pick(e.target.files)
            e.target.value = ''
          }}
        />
        <div className="btn-row upload-actions">
          <button className="btn" onClick={() => input.current?.click()} disabled={busy}>
            {picked.length ? 'Add more files' : 'Choose files'}
          </button>
          <button className="btn primary" onClick={() => run(picked)} disabled={busy || picked.length === 0}>
            {busy ? 'Working…' : picked.length ? `Upload ${picked.length} ${picked.length === 1 ? 'file' : 'files'}` : 'Upload'}
          </button>
        </div>
        {picked.length > 0 && results.length === 0 && (
          <ul className="file-list">
            {picked.map((f) => (
              <li key={f.name}>
                <span className="file-name">{f.name}</span>
                <span className="muted small">{Math.max(1, Math.round(f.data.length / 1024))} KB</span>
                <button
                  type="button"
                  className="btn ghost small"
                  onClick={() => remove(f.name)}
                  disabled={busy}
                  aria-label={`Remove ${f.name}`}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {busy && progress && (
        <div className="card upload-progress" aria-live="polite">
          <div className="progress">
            <div
              className="bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress.fraction * 100)}
            >
              <div style={{ width: `${Math.max(3, progress.fraction * 100)}%` }} />
            </div>
            <span>{Math.round(progress.fraction * 100)}%</span>
          </div>
          <p className="muted small">
            {progress.step}.{' '}
            {canRunInBackground
              ? 'You can switch apps or lock the phone: it keeps going, with progress in your notifications.'
              : 'You can look at other tabs meanwhile; keep this page open.'}
          </p>
        </div>
      )}

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

/** "2026-09" moved by `by` months. */
function addMonths(ym: string, by: number): string {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m - 1 + by, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** Which of your banks' statements are in for a month: ticked once the month has rows from that
 * bank. Your banks are the ones with statements within six months of it. Defaults to last month
 * (statements come out after the month ends). */
function Checklist() {
  const load = useLoad((b) => b.statementMonths())
  const [month, setMonth] = useStored('upload.checkMonth', addMonths(new Date().toISOString().slice(0, 7), -1))
  const [y, m] = month.split('-').map(Number)
  const near = new Set(Array.from({ length: 13 }, (_, i) => addMonths(month, i - 6)))
  const banks = Object.entries(load.data ?? {})
    .filter(([, months]) => Object.keys(months).some((x) => near.has(x)))
    .map(([source, months]) => ({ source, rows: months[month] ?? 0 }))
    .sort((a, b) => a.source.localeCompare(b.source))
  const done = banks.filter((b) => b.rows > 0).length
  return (
    <section className="card checklist" aria-labelledby="checklist-title">
      <div className="month-nav" data-tour="upload-checklist">
        <button type="button" className="icon-btn" onClick={() => setMonth(addMonths(month, -1))} aria-label="Previous month">
          ‹
        </button>
        <h3 id="checklist-title">{monthName(y, m)} statements</h3>
        <button type="button" className="icon-btn" onClick={() => setMonth(addMonths(month, 1))} aria-label="Next month">
          ›
        </button>
      </div>
      {load.error ? (
        <p className="small">Couldn't read your uploads: {load.error}</p>
      ) : !load.data ? (
        <p className="muted small">Checking your uploads…</p>
      ) : !banks.length ? (
        <p className="muted small">Your banks show up here once you've uploaded a statement from around this month.</p>
      ) : (
        <>
          <p className="muted small">
            {done === banks.length ? 'All in.' : `${done} of ${banks.length} uploaded.`}
          </p>
          <ul className="check-list">
            {banks.map((b) => (
              <li key={b.source} className={b.rows ? 'done' : ''}>
                <span className="check-mark" aria-hidden>
                  {b.rows ? '✓' : ''}
                </span>
                <span className="check-name">
                  {b.source}
                  <span className="muted small">{b.rows ? `${b.rows} ${b.rows === 1 ? 'transaction' : 'transactions'}` : 'Not uploaded yet'}</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
