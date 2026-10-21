import { useLoad } from '../app/context'
import { dayMonth, rm, shortDate } from '../app/format'
import { href } from '../app/router'
import type { TripDetail, TripRow } from '../data/Backend'
import { ErrorBox, Loading } from '../components/ui'

/** Every trip (Settings › Trips) with its total; tap one for its tab's blocks. */
export function Trips({ trip }: { trip?: string }) {
  return trip ? <Trip name={trip} /> : <TripList />
}

function TripList() {
  const load = useLoad((b) => b.listTrips())
  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />
  if (!load.data.length) {
    return (
      <div className="card">
        <p>No trips yet.</p>
        <p className="muted small">
          Add one in <a href={href({ name: 'settings', tab: 'trips' })}>Settings › Trips</a>: its spending moves to its own
          tab, and its total comes off the month it ends.
        </p>
      </div>
    )
  }
  const years = [...new Set(load.data.map((t) => t.year))]
  return (
    <div className="stack">
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
      <p className="muted small">
        Dates, currencies and rates are in <a href={href({ name: 'settings', tab: 'trips' })}>Settings › Trips</a>.
      </p>
    </div>
  )
}

function Trip({ name }: { name: string }) {
  const load = useLoad((b) => b.tripDetail(name), [name])
  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />
  const t: TripDetail = load.data
  return (
    <div className="stack">
      <a href={href({ name: 'trips' })} className="link-hint">
        ← All trips
      </a>
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
          <p className="muted small">
            A currency without a rate isn't counted yet: set it in{' '}
            <a href={href({ name: 'settings', tab: 'trips' })}>Settings › Trips</a>.
          </p>
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
    </div>
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
          {rows.map((r, i) => (
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
