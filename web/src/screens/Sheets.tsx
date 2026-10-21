import { useState } from 'react'
import { errorText, useData, useLoad } from '../app/context'
import { newestFirst, shortDate } from '../app/format'
import { go, href } from '../app/router'
import { Chips, Empty, ErrorBox, Field, Loading, Sheet } from '../components/ui'
import { INVESTMENTS, isInvestment, sheetCategory, type CustomSheet, type SheetRow, type SheetTable, type SheetTableRows } from '../data/Backend'

const COUNTS: Record<CustomSheet['counts'], string> = {
  earnings: 'Counts as earnings',
  spending: 'Counts as spending',
  '': 'Not counted in totals',
}
const CURRENCIES = ['RM', 'SGD', 'JPY', 'USD', 'THB', 'KRW', 'TWD', 'HKD', 'CNY', 'IDR', 'EUR', 'GBP', 'AUD']

/** "Chinese New Year 2026" under Chinese New Year adds nothing: show the tables instead. */
function sameAsGroup(name: string, group: string): boolean {
  return sheetCategory({ name }) === group
}

function money(amount: number, currency: string): string {
  const n = amount.toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return currency.toUpperCase() === 'RM' || currency.toUpperCase() === 'MYR' ? `RM ${n}` : `${n} ${currency}`
}

type Section = 'sheets' | 'investments'

/** On: the sheet's RM tables are added to the year's earnings or spending (Year End Summary, Home). */
function CountsToggle({ value, onChange, disabled, invest }: { value: CustomSheet['counts']; onChange(v: CustomSheet['counts']): void; disabled?: boolean; invest?: boolean }) {
  // Money put into investments leaves your account like spending; other sheets (ang pao) are usually earnings.
  const first = invest ? 'spending' : 'earnings'
  return (
    <div className="stack tight">
      <label className="toggle">
        <input type="checkbox" checked={value !== ''} disabled={disabled}
          onChange={(e) => onChange(e.target.checked ? first : '')} />
        <span className="switch" aria-hidden />
        <span>
          Count in the year's totals
          <span className="muted small"> · {value ? 'its RM tables are added to the Year End Summary and Home' : 'kept for reference only'}</span>
        </span>
      </label>
      {value !== '' && (
        <Chips<'earnings' | 'spending'> label="Counts as" options={['earnings', 'spending']} value={value}
          names={{ earnings: 'As earnings', spending: 'As spending' }}
          onChange={(v) => !disabled && onChange(v || value)} />
      )}
    </div>
  )
}

/** Your own sheets: tabs like "Chinese New Year" made of tables you define. Sheets in the
 * Investments category are on their own tab (section "investments"). */
export function Sheets({ sheet, section = 'sheets' }: { sheet?: string; section?: Section }) {
  return sheet ? <SheetView name={sheet} section={section} /> : <SheetList section={section} />
}

function SheetList({ section }: { section: Section }) {
  const load = useLoad((b) => b.listSheets())
  const [adding, setAdding] = useState(false)
  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />
  const invest = section === 'investments'
  const mine = load.data.filter((s) => isInvestment(s) === invest)
  // Grouped by category (e.g. every year's Chinese New Year together), newest year first.
  const groups = [...new Set(mine.map(sheetCategory))].sort((a, b) => a.localeCompare(b))

  return (
    <div className="stack">
      <p className="muted">
        {invest
          ? 'Your investment sheets: what you put in, took out or earned, in tables of your own. Any sheet in the Investments category shows here.'
          : "Sheets of your own, next to the months in that year's spreadsheet: ang pao, a side business, savings for something. Each has one or more tables (Date, a name column, Amount, Remarks), in RM or another currency."}
      </p>
      <div className="btn-row">
        <button className="btn primary" onClick={() => setAdding(true)}>
          {invest ? '+ New investment sheet' : '+ New sheet'}
        </button>
      </div>
      {mine.length === 0 &&
        (invest ? (
          <Empty title="No investment sheets yet">Make one, or set a sheet's category to Investments.</Empty>
        ) : (
          <Empty title="No sheets yet">Make one for anything that isn't a month or a trip.</Empty>
        ))}
      {groups.map((g) => (
        <section key={g} className="card flush">
          <h3 className="list-title">{invest && groups.length === 1 ? 'Sheets' : g}</h3>
          <ul className="rows">
            {mine.filter((s) => sheetCategory(s) === g).sort((a, b) => b.year - a.year || a.name.localeCompare(b.name)).map((s) => (
              <li key={s.name}>
                <a className="row" href={href({ name: section, sheet: s.name })}>
                  {/* The year leads; the name only when it says more than the group does. */}
                  <span className="row-date year">{s.year}</span>
                  <span className="row-main">
                    {!sameAsGroup(s.name, g) && <span className="row-item">{s.name}</span>}
                    <span className={sameAsGroup(s.name, g) ? 'row-item' : 'row-sub'}>
                      <span>{s.tables.map((t) => t.name).filter((n) => n !== s.name).join(' · ') || `${s.tables.length} ${s.tables.length === 1 ? 'table' : 'tables'}`}</span>
                    </span>
                    <span className="row-sub">
                      <span className={s.counts ? 'pos' : ''}>{COUNTS[s.counts]}</span>
                    </span>
                  </span>
                  <span className="chev" aria-hidden>
                    ›
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {adding && <SheetForm existing={load.data} section={section} onClose={() => setAdding(false)} />}
    </div>
  )
}

function SheetView({ name, section }: { name: string; section: Section }) {
  const { backend, changed, toast } = useData()
  const [saving, setSaving] = useState(false)
  const sheets = useLoad((b) => b.listSheets())
  const load = useLoad((b) => b.sheetRows(name), [name])
  const [editing, setEditing] = useState(false)
  const [row, setRow] = useState<{ table: SheetTableRows; row?: SheetRow }>()
  const link = useLoad((b) => b.sheetLink(name), [name])
  const sheet = sheets.data?.find((s) => s.name === name)

  if (load.error || sheets.error) return <ErrorBox message={(load.error ?? sheets.error)!} retry={load.reload} />
  if (!load.data || !sheets.data) return <Loading />
  if (!sheet) return <Empty title="Sheet not found"><a className="btn" href={href({ name: section })}>All sheets</a></Empty>

  return (
    <div className="stack">
      <div className="btn-row">
        <a className="btn ghost" href={href({ name: section })}>
          ‹ {section === 'investments' ? 'All investments' : 'All sheets'}
        </a>
        {link.data && (
          <a className="btn ghost push-left-auto" href={link.data} target="_blank" rel="noreferrer"
            title="Edit this sheet yourself in Google Sheets">
            Open in Google Sheets ↗
          </a>
        )}
        <button className={link.data ? 'btn' : 'btn push-left-auto'} onClick={() => setEditing(true)}>
          Edit sheet
        </button>
      </div>
      <h2 className="grow">
        {sheet.name} <span className="muted small">{sheet.year} · {sheetCategory(sheet)} · {COUNTS[sheet.counts]}</span>
      </h2>
      <section className="card">
        <CountsToggle value={sheet.counts} disabled={saving} invest={isInvestment(sheet)} onChange={async (counts) => {
          setSaving(true)
          try {
            await backend.saveSheet({ ...sheet, counts }, sheet.name)
            toast(counts ? `Counted as ${counts}` : 'Not counted in totals')
            changed()
          } catch (e) {
            toast(errorText(e))
          } finally {
            setSaving(false)
          }
        }} />
      </section>
      <div className="lists-pair">
        {load.data.map((t) => (
          <section key={t.index} className="card flush">
            <h3 className="list-title">
              {t.name} <span className="muted small">{t.rows.length}</span>
              <span className="push-right">{money(t.total, t.currency)}</span>
            </h3>
            {t.rows.length === 0 ? (
              <p className="muted pad">None yet.</p>
            ) : (
              <ul className="rows">
                {newestFirst(t.rows).map((r) => (
                  <li key={r.key || `${r.date}-${r.item}`}>
                    <button className="row" onClick={() => r.key && setRow({ table: t, row: r })} disabled={!r.key}>
                      <span className="row-date">{r.date ? shortDate(r.date) : ''}</span>
                      <span className="row-main">
                        <span className="row-item">{r.item || '—'}</span>
                        {r.remarks && <span className="row-sub">{r.remarks}</span>}
                      </span>
                      <span className="row-amt pos">{money(r.amount, t.currency)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="pad">
              <button className="btn" onClick={() => setRow({ table: t })}>
                + Add to {t.name}
              </button>
            </div>
          </section>
        ))}
      </div>
      {editing && <SheetForm sheet={sheet} existing={sheets.data} section={section} onClose={() => setEditing(false)} />}
      {row && <RowForm sheet={sheet.name} table={row.table} row={row.row} onClose={() => setRow(undefined)} />}
    </div>
  )
}

function SheetForm({ sheet, existing, section, onClose }: { sheet?: CustomSheet; existing: CustomSheet[]; section: Section; onClose(): void }) {
  const { backend, changed, toast } = useData()
  const [s, setS] = useState<CustomSheet>(
    sheet ? { ...sheet, category: sheetCategory(sheet) } : {
      name: '', year: new Date().getFullYear(), counts: '', category: section === 'investments' ? INVESTMENTS : '',
      tables: [{ name: 'Table 1', currency: 'RM', label: 'Item' }],
    },
  )
  const categories = [...new Set([INVESTMENTS, ...existing.map(sheetCategory)])].sort()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [deleting, setDeleting] = useState(false)
  const kept = sheet?.tables.length ?? 0

  async function remove(deleteTab: boolean) {
    if (!sheet) return
    setBusy(true)
    setError(undefined)
    try {
      await backend.deleteSheet(sheet.name, deleteTab)
      toast(deleteTab ? `Deleted "${sheet.name}"` : `"${sheet.name}" removed from the app (its tab is kept)`)
      changed()
      onClose()
      go({ name: section })
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  } // existing tables can be renamed, not removed (their rows stay in place)
  const taken = existing.some((x) => x.name.toLowerCase() === s.name.trim().toLowerCase() && x.name !== sheet?.name)
  const reserved = /^(january|february|march|april|may|june|july|august|september|october|november|december) \d{4}$|^(to update|year end summary)$/i.test(s.name.trim())
  const valid = s.name.trim() && !taken && !reserved && s.tables.length > 0 && s.tables.every((t) => t.name.trim())

  function setTable(i: number, t: Partial<SheetTable>) {
    setS({ ...s, tables: s.tables.map((x, j) => (j === i ? { ...x, ...t } : x)) })
  }

  async function save() {
    setBusy(true)
    setError(undefined)
    try {
      const clean = { ...s, name: s.name.trim(), category: (s.category ?? '').trim() || sheetCategory({ name: s.name.trim() }), tables: s.tables.map((t) => ({ name: t.name.trim(), currency: t.currency.trim() || 'RM', label: t.label.trim() || 'Item' })) }
      await backend.saveSheet(clean, sheet?.name)
      toast(sheet ? 'Sheet saved' : `Made "${clean.name}"`)
      changed()
      onClose()
      if (!sheet || sheet.name !== clean.name || isInvestment(clean) !== isInvestment(sheet)) {
        go({ name: isInvestment(clean) ? 'investments' : 'sheets', sheet: clean.name })
      }
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  return (
    <Sheet title={sheet ? 'Edit sheet' : 'New sheet'} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); if (valid) save() }}>
        <div className="two">
          <Field label="Name" hint={taken ? 'You already have a sheet with this name' : reserved ? 'That name is taken by the app' : 'e.g. Chinese New Year'}>
            <input value={s.name} onChange={(e) => setS({ ...s, name: e.target.value })} autoFocus={!sheet} />
          </Field>
          <Field label="Year" hint={sheet ? "Can't change" : 'Which spreadsheet it goes in'}>
            <input type="number" value={s.year} disabled={!!sheet} onChange={(e) => setS({ ...s, year: Number(e.target.value) })} />
          </Field>
        </div>
        <Field label="Category" hint="Groups your sheets, e.g. every year's Chinese New Year together. Investments: on the Investments tab.">
          <input value={s.category ?? ''} onChange={(e) => setS({ ...s, category: e.target.value })} list="sheet-categories"
            placeholder={s.name.trim() ? sheetCategory({ name: s.name }) : 'e.g. Chinese New Year'} />
          <datalist id="sheet-categories">
            {categories.map((c) => <option key={c} value={c} />)}
          </datalist>
        </Field>
        <CountsToggle value={s.counts} invest={isInvestment(s)} onChange={(counts) => setS({ ...s, counts })} />
        <h3>Tables</h3>
        {s.tables.map((t, i) => (
          <div key={i} className="table-row">
            <Field label="Table name">
              <input value={t.name} onChange={(e) => setTable(i, { name: e.target.value })} />
            </Field>
            <Field label="Currency">
              <input value={t.currency} onChange={(e) => setTable(i, { currency: e.target.value })} list="sheet-currencies" />
            </Field>
            <Field label="Name column">
              <input value={t.label} onChange={(e) => setTable(i, { label: e.target.value })} placeholder="Item, Person…" />
            </Field>
            {i >= kept && s.tables.length > 1 && (
              <button type="button" className="icon-btn" aria-label="Remove table"
                onClick={() => setS({ ...s, tables: s.tables.filter((_, j) => j !== i) })}>
                ✕
              </button>
            )}
          </div>
        ))}
        <datalist id="sheet-currencies">
          {CURRENCIES.map((c) => <option key={c} value={c} />)}
        </datalist>
        <div className="btn-row">
          <button type="button" className="btn" onClick={() => setS({ ...s, tables: [...s.tables, { name: `Table ${s.tables.length + 1}`, currency: 'RM', label: 'Item' }] })}>
            + Add table
          </button>
        </div>
        {error && <p className="error-text">{error}</p>}
        {sheet && !deleting && (
          <button type="button" className="btn ghost danger" onClick={() => setDeleting(true)}>
            Delete sheet…
          </button>
        )}
        {sheet && deleting && (
          <div className="card stack tight danger-box">
            <p className="small">
              Delete <strong>{sheet.name}</strong>? It stops counting in {sheet.year}'s totals either way.
            </p>
            <div className="btn-row">
              <button type="button" className="btn danger" disabled={busy} onClick={() => remove(true)}>
                Delete it and its tab
              </button>
              <button type="button" className="btn" disabled={busy} onClick={() => remove(false)}
                title="The tab and its rows stay in Google Sheets; the app just stops showing it">
                Remove from the app only
              </button>
              <button type="button" className="btn ghost" onClick={() => setDeleting(false)}>Keep it</button>
            </div>
            <p className="muted small">Deleting the tab deletes its rows in Google Sheets too (you can still undo it there with Ctrl+Z / version history).</p>
          </div>
        )}
        <div className="btn-row end">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy || !valid}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Sheet>
  )
}

function RowForm({ sheet, table, row, onClose }: { sheet: string; table: SheetTableRows; row?: SheetRow; onClose(): void }) {
  const { backend, changed, toast } = useData()
  const [f, setF] = useState({ date: row?.date ?? new Date().toISOString().slice(0, 10), item: row?.item ?? '', remarks: row?.remarks ?? '' })
  const [amount, setAmount] = useState(row ? String(row.amount) : '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const valid = Number(amount) > 0 && (f.item.trim() !== '' || f.date !== '')

  async function act(what: 'save' | 'delete') {
    setBusy(true)
    setError(undefined)
    try {
      const fields = { ...f, item: f.item.trim(), remarks: f.remarks.trim(), amount: Number(amount) }
      if (what === 'delete') await backend.deleteSheetRow(sheet, row!.key)
      else if (row) await backend.editSheetRow(sheet, row.key, fields)
      else await backend.addSheetRow(sheet, table.index, fields)
      toast(what === 'delete' ? 'Removed' : row ? 'Saved' : `Added to ${table.name}`)
      changed()
      onClose()
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  return (
    <Sheet title={row ? `Edit ${table.name}` : `Add to ${table.name}`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); if (valid) act('save') }}>
        <div className="two">
          <Field label="Date">
            <input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
          </Field>
          <Field label={`Amount (${table.currency})`}>
            <input type="number" inputMode="decimal" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
          </Field>
        </div>
        <Field label={table.label}>
          <input value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })} autoFocus={!row} />
        </Field>
        <Field label="Remarks" hint="Optional">
          <input value={f.remarks} onChange={(e) => setF({ ...f, remarks: e.target.value })} />
        </Field>
        {error && <p className="error-text">{error}</p>}
        <div className="btn-row end">
          {row && (
            <button type="button" className="btn ghost danger push-left" disabled={busy} onClick={() => act('delete')}>
              Delete
            </button>
          )}
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy || !valid}>{busy ? 'Saving…' : row ? 'Save' : 'Add'}</button>
        </div>
      </form>
    </Sheet>
  )
}
