import { useState } from 'react'
import { errorText, useData, useLoad } from '../app/context'
import { dayMonth, newestFirst, rm, shortDate } from '../app/format'
import { go, href } from '../app/router'
import { CURRENCIES, currencyCode, rateToRm } from '../data/fx'
import type { Trip as TripData, TripDetail, TripRow } from '../data/Backend'
import { ErrorBox, Field, Loading, Sheet } from '../components/ui'

/** Every trip with its total; tap one for its tab's blocks. Trips are added and changed here. */
export function Trips({ trip }: { trip?: string }) {
  return trip ? <Trip name={trip} /> : <TripList />
}

function TripList() {
  const load = useLoad((b) => b.listTrips())
  const [adding, setAdding] = useState(false)
  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />
  const years = [...new Set(load.data.map((t) => t.year))]
  return (
    <div className="stack">
      <div className="btn-row">
        <button type="button" className="btn primary" data-tour="add-trip" onClick={() => setAdding(true)}>
          + Add trip
        </button>
      </div>
      {!load.data.length && (
        <div className="card">
          <p>No trips yet.</p>
          <p className="muted small">A trip's spending moves to its own tab, and its total comes off the month it ends.</p>
        </div>
      )}
      {years.map((y) => (
        <section key={y} className="card flush">
          <h3 className="list-title">{y}</h3>
          <ul className="rows">
            {load.data!.filter((t) => t.year === y).map(({ trip, total }) => (
              <li key={trip.name}>
                <a className="row" href={href({ name: 'trips', trip: trip.name })}>
                  <span className="row-main">
                    <span className="row-item">{trip.name}</span>
                    <span className="row-sub">
                      <span>
                        {shortDate(trip.start)} – {shortDate(trip.end)}
                      </span>
                      {trip.currencies.length > 0 && <span>{trip.currencies.map((c) => c.code).join(', ')}</span>}
                    </span>
                  </span>
                  <span className="row-amt">{total === null ? <span className="muted small">No tab yet</span> : rm(total)}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {adding && <TripSheet taken={load.data.map((t) => t.trip.name)} onClose={() => setAdding(false)} />}
    </div>
  )
}

function Trip({ name }: { name: string }) {
  const load = useLoad((b) => b.tripDetail(name), [name])
  const settings = useLoad((b) => b.getSettings())
  const [editing, setEditing] = useState(false)
  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />
  const t: TripDetail = load.data
  const trip = settings.data?.trips.find((x) => x.name === name)
  return (
    <div className="stack">
      <div className="btn-row">
        <a href={href({ name: 'trips' })} className="link-hint">
          ← All trips
        </a>
        <button type="button" className="btn small push-right" disabled={!trip} onClick={() => setEditing(true)}>
          Edit trip
        </button>
      </div>
      <section className="card summary">
        <div className="eyebrow">
          {t.name} · {shortDate(t.start)} – {shortDate(t.end)}
        </div>
        <div className="totals">
          <div>
            <span className="label">Spent in RM</span>
            <span className="amount">{rm(t.spentRm)}</span>
          </div>
          {t.currencies.map((c) => (
            <div key={c.code}>
              <span className="label">
                {c.code} {c.spent.toLocaleString('en-MY')} × {c.rate ?? '?'}
              </span>
              <span className="amount">{c.rate ? rm(c.rm) : <span className="muted small">Set a rate</span>}</span>
            </div>
          ))}
          <div>
            <span className="label">Paid back to you</span>
            <span className="amount pos">−{rm(t.paidBack)}</span>
          </div>
          <div className="final-row">
            <span className="label">Trip total</span>
            <span className="amount">{rm(t.total)}</span>
          </div>
        </div>
        {t.currencies.some((c) => !c.rate) && (
          <p className="muted small">A currency without a rate isn't counted yet: set it with Edit trip.</p>
        )}
      </section>
      <div className="lists-pair">
        <TripRows title="Spending (RM)" rows={t.rm} money={rm} />
        <TripRows title="Paid back to you" rows={t.paid} money={rm} />
      </div>
      {t.currencies.map((c) => (
        <TripRows key={c.code} title={`Spending in ${c.code}`} rows={c.rows} money={(n) => `${c.code} ${n.toLocaleString('en-MY')}`} />
      ))}
      {t.received.length > 0 && (
        <TripRows
          title="Received in other currencies"
          rows={t.received}
          money={(n, r) => `${r.currency} ${n.toLocaleString('en-MY')}`}
        />
      )}
      <p className="muted small">To add or move rows, use + Add transaction or a row's Trip field on the Month screen.</p>
      {editing && trip && (
        <TripSheet trip={trip} taken={settings.data!.trips.map((x) => x.name).filter((n) => n !== name)} onClose={() => setEditing(false)} />
      )}
    </div>
  )
}

const RESERVED = /^(january|february|march|april|may|june|july|august|september|october|november|december) \d{4}$|^(to update|year end summary)$/i

function TripSheet({ trip, taken, onClose }: { trip?: TripData; taken: string[]; onClose(): void }) {
  const { backend, changed, toast } = useData()
  const [t, setT] = useState<TripData>(trip ?? { name: '', start: '', end: '', currencies: [], match: [] })
  const [match, setMatch] = useState((trip?.match ?? []).join(', '))
  const [rateBusy, setRateBusy] = useState<number>()
  const [rateNote, setRateNote] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [deleting, setDeleting] = useState(false)
  const setCur = (i: number, c: Partial<TripData['currencies'][number]>) =>
    setT({ ...t, currencies: t.currencies.map((x, j) => (j === i ? { ...x, ...c } : x)) })
  const name = t.name.trim()
  const nameTaken = taken.some((n) => n.toLowerCase() === name.toLowerCase())
  const nameReserved = RESERVED.test(name)
  const otherYear = !!trip && !!t.start && t.start.slice(0, 4) !== trip.start.slice(0, 4)
  const valid = name && !nameTaken && !nameReserved && t.start && t.end && t.start <= t.end && !otherYear

  async function save() {
    setBusy(true)
    setError(undefined)
    try {
      await backend.saveTrip(
        {
          ...t,
          name,
          currencies: t.currencies.map((c) => ({ ...c, code: c.code.trim().toUpperCase() })).filter((c) => c.code),
          match: match.split(',').map((m) => m.trim()).filter(Boolean),
          link: t.link?.trim() || undefined,
        },
        trip?.name,
      )
      toast(trip ? 'Trip saved' : `Added ${name}`)
      changed()
      onClose()
      if (trip && trip.name !== name) go({ name: 'trips', trip: name })
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setError(undefined)
    try {
      const left = await backend.deleteTrip(trip!.name)
      toast(left ? `Deleted ${trip!.name}. ${left} row(s) with no month stay on its tab, not counted.` : `Deleted ${trip!.name}`)
      changed()
      onClose()
      go({ name: 'trips' })
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  return (
    <Sheet title={trip ? 'Edit trip' : 'New trip'} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) save()
        }}
      >
        <Field label="Name" hint={nameTaken ? 'You already have a trip with this name' : nameReserved ? 'That name is taken by the app' : undefined}>
          <input value={t.name} onChange={(e) => setT({ ...t, name: e.target.value })} placeholder="e.g. Japan Trip" autoFocus={!trip} />
        </Field>
        <div className="two">
          <Field label="Start" hint={otherYear ? `Stays in ${trip!.start.slice(0, 4)}: add a new trip for another year` : undefined}>
            <input type="date" value={t.start} onChange={(e) => setT({ ...t, start: e.target.value })} />
          </Field>
          <Field label="End" hint={t.start && t.end && t.start > t.end ? 'Must be after the start' : undefined}>
            <input type="date" value={t.end} onChange={(e) => setT({ ...t, end: e.target.value })} />
          </Field>
        </div>
        <h3>Currencies</h3>
        <p className="muted small">Each gets its own spending block on the trip tab. None for a trip in RM only.</p>
        {t.currencies.map((c, i) => (
          <div key={i} className="table-row">
            <Field label="Currency">
              <input value={c.code} onChange={(e) => setCur(i, { code: e.target.value })} placeholder="e.g. JPY" list="currencies" />
            </Field>
            <Field label="RM per 1">
              <input type="number" inputMode="decimal" step="any" value={c.rate ?? ''}
                onChange={(e) => setCur(i, { rate: e.target.value ? Number(e.target.value) : undefined })} />
            </Field>
            <button type="button" className="btn small" disabled={!c.code.trim() || rateBusy === i}
              onClick={async () => {
                setRateBusy(i)
                setRateNote(undefined)
                try {
                  const rate = await rateToRm(c.code)
                  setCur(i, { rate: Number(rate.toPrecision(6)) })
                  setRateNote(`Today's rate: RM ${rate.toPrecision(6)} per 1 ${currencyCode(c.code)}`)
                } catch (e) {
                  setRateNote(errorText(e))
                } finally {
                  setRateBusy(undefined)
                }
              }}>
              {rateBusy === i ? 'Looking up…' : "Today's rate"}
            </button>
            <button type="button" className="icon-btn" aria-label={`Remove ${c.code || 'currency'}`}
              onClick={() => setT({ ...t, currencies: t.currencies.filter((_, j) => j !== i) })}>
              ✕
            </button>
          </div>
        ))}
        <datalist id="currencies">
          {CURRENCIES.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <div className="btn-row">
          <button type="button" className="btn" onClick={() => setT({ ...t, currencies: [...t.currencies, { code: '' }] })}>
            + Add currency
          </button>
          {rateNote && <span className="muted small">{rateNote}</span>}
        </div>
        <Field label="Earlier bookings containing" hint="Comma-separated, e.g. AIRASIA, AGODA">
          <input value={match} onChange={(e) => setMatch(e.target.value)} />
        </Field>
        <Field label="Itinerary link">
          <input type="url" value={t.link ?? ''} onChange={(e) => setT({ ...t, link: e.target.value })} />
        </Field>
        {error && <p className="error-text">{error}</p>}
        {trip && !deleting && (
          <button type="button" className="btn ghost danger" onClick={() => setDeleting(true)}>
            Delete trip…
          </button>
        )}
        {trip && deleting && (
          <div className="card stack tight danger-box">
            <p className="small">
              Delete <strong>{trip.name}</strong>? Its RM spending and money paid back go to the months they happened in.
              Anything in another currency stays on its tab in Google Sheets, not counted.
            </p>
            <div className="btn-row">
              <button type="button" className="btn danger" disabled={busy} onClick={remove}>
                Delete trip
              </button>
              <button type="button" className="btn ghost" onClick={() => setDeleting(false)}>
                Keep it
              </button>
            </div>
          </div>
        )}
        <div className="btn-row end">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy || !valid}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </Sheet>
  )
}

function TripRows({ title, rows, money }: { title: string; rows: TripRow[]; money(n: number, r: TripRow): string }) {
  return (
    <section className="card flush">
      <h3 className="list-title">
        {title} <span className="muted small">{rows.length}</span>
      </h3>
      {rows.length === 0 ? (
        <p className="muted pad">None.</p>
      ) : (
        <ul className="rows">
          {newestFirst(rows).map((r, i) => (
            <li key={i}>
              <div className="row">
                <span className="row-date">{r.date ? dayMonth(r.date) : ''}</span>
                <span className="row-main">
                  <span className="row-item">{r.item}</span>
                  <span className="row-sub">
                    {[r.category, r.importance, r.remarks, r.source].filter(Boolean).map((x, j) => (
                      <span key={j}>{x}</span>
                    ))}
                  </span>
                </span>
                <span className="row-amt">{money(r.amount, r)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
