import { useState } from 'react'
import { errorText, useData, useLoad } from '../app/context'
import { dayMonth, monthName, rm, signedRm } from '../app/format'
import { href } from '../app/router'
import { CategoryPicker } from '../components/CategoryPicker'
import { Chips, Empty, ErrorBox, Field, Loading, Sheet } from '../components/ui'
import { IMPORTANCE, type MonthSummary, type Row } from '../data/Backend'

export function Month({ year, month }: { year?: number; month?: number }) {
  const months = useLoad((b) => b.listMonths())
  const list = months.data ?? []
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
      </div>
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
        {/* Side by side when there's room, as in the sheet; stacked on a phone. */}
        <div className="lists-pair">
          <RowList title="Spendings" rows={spend} onTap={setEditing} />
          <RowList title="Earnings" rows={earn} onTap={setEditing} />
        </div>
        {trip.length > 0 && <RowList title="Trips" rows={trip} onTap={setEditing} />}
      </div>
      {editing && <EditRow row={editing} onClose={() => setEditing(undefined)} />}
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
  const [f, setF] = useState({ item: row.item, category: row.category, importance: row.importance, remarks: row.remarks })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const isSpend = row.kind === 'spend'

  async function save() {
    setBusy(true)
    try {
      await backend.editRow(row.key, isSpend ? f : { item: f.item, remarks: f.remarks })
      toast('Row updated')
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
        <Field label="Remarks">
          <input value={f.remarks} onChange={(e) => setF({ ...f, remarks: e.target.value })} />
        </Field>
        {error && <p className="error-text">{error}</p>}
        <div className="btn-row end">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy || !f.item.trim()}>
            Save
          </button>
        </div>
      </form>
    </Sheet>
  )
}
