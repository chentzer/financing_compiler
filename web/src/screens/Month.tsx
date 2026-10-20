import { useState } from 'react'
import { errorText, useData, useLoad } from '../app/context'
import { dayMonth, monthName, rm, signedRm } from '../app/format'
import { go, href } from '../app/router'
import { CategoryPicker } from '../components/CategoryPicker'
import { Chips, Empty, ErrorBox, Field, Loading, Sheet } from '../components/ui'
import { IMPORTANCE, STATEMENT_SOURCES, type Kind, type Month as MonthT, type MonthSummary, type NewRow, type Row, type Trip } from '../data/Backend'

export function Month({ year, month }: { year?: number; month?: number }) {
  const months = useLoad((b) => b.listMonths())
  const list = months.data ?? []
  const [picking, setPicking] = useState(false)
  const now = new Date()
  const target =
    (year && list.find((m) => m.year === year && m.month === month)) ||
    list.find((m) => m.year === now.getFullYear() && m.month === now.getMonth() + 1) ||
    list.at(-1)

  if (months.error) return <ErrorBox message={months.error} retry={months.reload} />
  if (!months.data) return <Loading />
  if (!target) return <Empty title="No months yet">Upload statements to see a month.</Empty>

  const i = list.findIndex((m) => m.year === target.year && m.month === target.month)
  const prev = list[i - 1]
  const next = list[i + 1]

  return (
    <div className="stack">
      <div className="month-nav">
        <a className={prev ? 'icon-btn' : 'icon-btn disabled'} href={prev ? href({ name: 'month', ...prev }) : undefined} aria-label="Previous month">
          ‹
        </a>
        <h2>{monthName(target.year, target.month)}</h2>
        <a className={next ? 'icon-btn' : 'icon-btn disabled'} href={next ? href({ name: 'month', ...next }) : undefined} aria-label="Next month">
          ›
        </a>
        <button className="icon-btn" onClick={() => setPicking(true)} aria-label="Choose month and year" title="Choose month and year">
          <CalendarIcon />
        </button>
      </div>
      {picking && <MonthPicker months={list} current={target} onClose={() => setPicking(false)} />}
      <MonthBody year={target.year} month={target.month} />
    </div>
  )
}

function MonthBody({ year, month }: { year: number; month: number }) {
  const load = useLoad(
    async (b) => {
      const [summary, rows] = await Promise.all([b.monthSummary(year, month), b.monthRows(year, month)])
      return { summary, rows }
    },
    [year, month],
  )
  const [editing, setEditing] = useState<Row>()
  const [adding, setAdding] = useState(false)

  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />
  const { summary, rows } = load.data
  const spend = rows.filter((r) => r.kind === 'spend' && !r.trip)
  const earn = rows.filter((r) => r.kind === 'earn')
  const trip = rows.filter((r) => r.trip)

  return (
    <div className="month-grid">
      <Summary s={summary} />
      <div className="stack">
        <div className="btn-row end">
          <button className="btn" onClick={() => setAdding(true)}>
            + Add transaction
          </button>
        </div>
        {/* Side by side when there's room, as in the sheet; stacked on a phone. */}
        <div className="lists-pair">
          <RowList title="Spendings" rows={spend} onTap={setEditing} />
          <RowList title="Earnings" rows={earn} onTap={setEditing} />
        </div>
        {trip.length > 0 && <RowList title="Trips" rows={trip} onTap={setEditing} />}
      </div>
      {editing && <EditRow row={editing} onClose={() => setEditing(undefined)} />}
      {adding && <AddRow year={year} month={month} onClose={() => setAdding(false)} />}
    </div>
  )
}

function Summary({ s }: { s: MonthSummary }) {
  const maxCat = Math.max(1, ...s.byCategory.map((c) => c.amount))
  const maxImp = Math.max(1, ...s.byImportance.map((c) => c.amount))
  return (
    <section className="card summary">
      <div className="totals">
        <div>
          <span className="label">Earnings</span>
          <span className="amount pos">{rm(s.earnings)}</span>
        </div>
        <div>
          <span className="label">Spendings</span>
          <span className="amount">{rm(s.spendings)}</span>
        </div>
        {s.trips.map((t) => (
          <div key={t.name}>
            <span className="label">{t.name}</span>
            <span className="amount">{rm(t.total)}</span>
          </div>
        ))}
        <div className="final-row">
          <span className="label">Final</span>
          <span className={s.final < 0 ? 'amount neg' : 'amount pos'}>{rm(s.final)}</span>
        </div>
      </div>
      <h3>By Category</h3>
      <Bars items={s.byCategory} max={maxCat} />
      <h3>By Importance</h3>
      <Bars items={s.byImportance} max={maxImp} />
    </section>
  )
}

function Bars({ items, max }: { items: { name: string; amount: number }[]; max: number }) {
  return (
    <ul className="bars">
      {items.map((c) => (
        <li key={c.name || '(blank)'} className={c.amount === 0 ? 'zero' : ''}>
          <span className="bar-name">{c.name || 'Not set'}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(c.amount / max) * 100}%` }} />
          </span>
          <span className="bar-amt">{c.amount ? rm(c.amount) : '–'}</span>
        </li>
      ))}
    </ul>
  )
}

function RowList({ title, rows, onTap }: { title: string; rows: Row[]; onTap(r: Row): void }) {
  return (
    <section className="card flush">
      <h3 className="list-title">
        {title} <span className="muted small">{rows.length}</span>
      </h3>
      {rows.length === 0 ? (
        <p className="muted pad">None.</p>
      ) : (
        <ul className="rows">
          {rows.map((r) => (
            <li key={r.key}>
              <button className="row" onClick={() => onTap(r)}>
                <span className="row-date">{dayMonth(r.date)}</span>
                <span className="row-main">
                  <span className="row-item">{r.item}</span>
                  <span className="row-sub">
                    {[r.kind === 'spend' && (r.category || <em key="c">No category</em>), r.importance, r.remarks, r.trip, r.source]
                      .filter(Boolean)
                      .map((x, i) => (
                        <span key={i}>{x}</span>
                      ))}
                  </span>
                </span>
                <span className={r.kind === 'earn' ? 'row-amt pos' : 'row-amt'}>{signedRm(r.amount, r.kind)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function EditRow({ row, onClose }: { row: Row; onClose(): void }) {
  const { backend, changed, toast } = useData()
  const [f, setF] = useState({
    item: row.item, category: row.category, importance: row.importance, remarks: row.remarks, source: row.source,
  })
  const trips = useLoad((b) => b.getSettings().then((s) => s.trips))
  const [moveTo, setMoveTo] = useState(row.trip ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const isSpend = row.kind === 'spend'
  const byHand = row.key.startsWith('manual:') // typed straight into the sheet: no key to find it by

  async function save() {
    setBusy(true)
    try {
      await backend.editRow(row.key, isSpend ? f : { item: f.item, remarks: f.remarks, source: f.source })
      if (isSpend && moveTo !== (row.trip ?? '')) await backend.moveRow(row.key, moveTo || null)
      toast(moveTo !== (row.trip ?? '') ? (moveTo ? `Moved to ${moveTo}` : 'Moved back to its month') : 'Row updated')
      changed()
      onClose()
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  return (
    <Sheet title={`${dayMonth(row.date)} · ${signedRm(row.amount, row.kind)}`} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        <p className="muted small">
          {row.source}
          {row.trip ? ` · ${row.trip}` : ''}
        </p>
        <Field label="Item">
          <input value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })} />
        </Field>
        {isSpend && (
          <>
            <Field label="Category">
              <CategoryPicker value={f.category} onChange={(v) => setF({ ...f, category: v })} />
            </Field>
            <Field label="Importance">
              <Chips label="Importance" options={IMPORTANCE} value={f.importance} onChange={(v) => setF({ ...f, importance: v })} />
            </Field>
          </>
        )}
        <SourceField value={f.source} onChange={(source) => setF({ ...f, source })} />
        <Field label="Remarks" hint="Your own note">
          <input value={f.remarks} onChange={(e) => setF({ ...f, remarks: e.target.value })} />
        </Field>
        {isSpend && !byHand && (trips.data?.length ?? 0) > 0 && (
          <Field label="Trip" hint="Move this spending onto a trip's tab">
            <select value={moveTo} onChange={(e) => setMoveTo(e.target.value)}>
              <option value="">Not on a trip (its month)</option>
              {trips.data!.map((t) => (
                <option key={t.name}>{t.name}</option>
              ))}
            </select>
          </Field>
        )}
        {byHand && <p className="muted small">This row was typed straight into the sheet, so edit it there.</p>}
        {error && <p className="error-text">{error}</p>}
        <div className="btn-row end">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy || byHand || !f.item.trim()}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </Sheet>
  )
}

const SOURCES = [...STATEMENT_SOURCES.map((s) => s.label), 'Cash']

/** Bank, wallet or anything you type (e.g. "Cash"). */
function SourceField({ value, onChange }: { value: string; onChange(v: string): void }) {
  return (
    <Field label="Source" hint="Bank or wallet it's from">
      <input value={value} onChange={(e) => onChange(e.target.value)} list="sources" placeholder="e.g. Maybank, Cash" />
      <datalist id="sources">
        {SOURCES.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
    </Field>
  )
}

function AddRow({ year, month, onClose }: { year: number; month: number; onClose(): void }) {
  const { backend, changed, toast } = useData()
  const trips = useLoad((b) => b.getSettings().then((s) => s.trips))
  const today = new Date()
  const inMonth = today.getFullYear() === year && today.getMonth() + 1 === month
  const firstDay = `${year}-${String(month).padStart(2, '0')}-01`
  const [f, setF] = useState<NewRow>({
    kind: 'spend', date: inMonth ? today.toISOString().slice(0, 10) : firstDay, item: '', amount: 0,
    category: '', importance: '', source: '', remarks: '', trip: '',
  })
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const isSpend = f.kind === 'spend'
  const trip: Trip | undefined = trips.data?.find((t) => t.name === f.trip)
  const valid = f.item.trim() !== '' && Number(amount) > 0 && !!f.date

  async function save() {
    setBusy(true)
    setError(undefined)
    try {
      await backend.addRow({ ...f, amount: Number(amount), trip: f.trip || undefined,
        currency: isSpend && trip ? f.currency || undefined : undefined })
      toast(f.trip ? (isSpend ? `Added to ${f.trip}` : `Added to ${f.trip} as paid back to you`) : 'Added')
      changed()
      onClose()
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  return (
    <Sheet title="Add transaction" onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) save()
        }}
      >
        <Chips<Kind>
          label="Spending or earning"
          options={['spend', 'earn']}
          value={f.kind}
          onChange={(k) => setF({ ...f, kind: k || f.kind })}
          names={{ spend: 'Spending', earn: 'Earning' }}
        />
        <div className="two">
          <Field label="Date">
            <input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
          </Field>
          <Field label={`Amount (${(isSpend && f.currency) || 'RM'})`}>
            <input type="number" inputMode="decimal" step="0.01" min="0" value={amount}
              onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
          </Field>
        </div>
        <Field label="Item">
          <input value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })} placeholder="e.g. Dinner" autoFocus />
        </Field>
        {(trips.data?.length ?? 0) > 0 && (
          <Field label="Trip" hint={isSpend ? undefined : 'Money in on a trip is "paid back to you"'}>
            <select value={f.trip} onChange={(e) => setF({ ...f, trip: e.target.value, currency: '' })}>
              <option value="">Not on a trip</option>
              {trips.data!.map((t) => (
                <option key={t.name}>{t.name}</option>
              ))}
            </select>
          </Field>
        )}
        {isSpend && trip && trip.currencies.length > 0 && (
          <Field label="Paid in">
            <Chips<string>
              label="Currency"
              options={['RM', ...trip.currencies.map((c) => c.code)]}
              value={f.currency || 'RM'}
              onChange={(c) => setF({ ...f, currency: c && c !== 'RM' ? c : '' })}
            />
          </Field>
        )}
        {isSpend && (
          <>
            <Field label="Category">
              <CategoryPicker value={f.category ?? ''} onChange={(v) => setF({ ...f, category: v })} />
            </Field>
            <Field label="Importance" hint="Optional">
              <Chips label="Importance" options={IMPORTANCE} value={f.importance ?? ''} onChange={(v) => setF({ ...f, importance: v })} />
            </Field>
          </>
        )}
        {!(isSpend && f.currency) && !(f.trip && !isSpend) && (
          <SourceField value={f.source ?? ''} onChange={(source) => setF({ ...f, source })} />
        )}
        <Field label="Remarks" hint="Optional">
          <input value={f.remarks} onChange={(e) => setF({ ...f, remarks: e.target.value })} />
        </Field>
        {error && <p className="error-text">{error}</p>}
        <div className="btn-row end">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy || !valid}>
            {busy ? 'Adding…' : 'Add'}
          </button>
        </div>
      </form>
    </Sheet>
  )
}

const SHORT_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function CalendarIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 10h18M8 3v4M16 3v4" />
    </svg>
  )
}

/** Pick a year, then a month; months without a tab are greyed out. */
function MonthPicker({ months, current, onClose }: { months: MonthT[]; current: MonthT; onClose(): void }) {
  const years = [...new Set(months.map((m) => m.year))].sort((a, b) => a - b)
  const [year, setYear] = useState(current.year)
  const yi = years.indexOf(year)
  const has = (m: number) => months.some((x) => x.year === year && x.month === m)
  return (
    <Sheet title="Choose a month" onClose={onClose}>
      <div className="stack">
        <div className="month-nav picker-year">
          <button className="icon-btn" disabled={yi <= 0} onClick={() => setYear(years[yi - 1])} aria-label="Previous year">
            ‹
          </button>
          <h2>{year}</h2>
          <button className="icon-btn" disabled={yi >= years.length - 1} onClick={() => setYear(years[yi + 1])} aria-label="Next year">
            ›
          </button>
        </div>
        <div className="month-picker">
          {SHORT_MONTHS.map((name, i) => {
            const m = i + 1
            const on = year === current.year && m === current.month
            return (
              <button
                key={name}
                className={on ? 'chip on' : 'chip'}
                disabled={!has(m)}
                onClick={() => {
                  go({ name: 'month', year, month: m })
                  onClose()
                }}
              >
                {name}
              </button>
            )
          })}
        </div>
        <p className="muted small">Greyed-out months have no tab yet.</p>
      </div>
    </Sheet>
  )
}
