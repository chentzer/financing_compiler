import { useLoad } from '../app/context'
import { monthName, rm, shortDate } from '../app/format'
import { href } from '../app/router'
import { ErrorBox, Loading } from '../components/ui'
import { MonthBars, Totals } from './Home'
import { Bars } from './Month'

/** One year: its totals (as the Year End Summary), each month, by category, and its trips. */
export function Year({ year }: { year?: number }) {
  const years = useLoad((b) => b.listYears())
  const now = new Date().getFullYear()
  const shown = year ?? (years.data?.includes(now) ? now : years.data?.at(-1))
  const load = useLoad(async (b) => {
    if (shown === undefined) return null
    const [summary, trips] = await Promise.all([b.yearSummary(shown), b.listTrips()])
    return { summary, trips: trips.filter((t) => t.year === shown) }
  }, [shown])

  if (years.error) return <ErrorBox message={years.error} retry={years.reload} />
  if (!years.data) return <Loading />
  if (!years.data.length) {
    return (
      <div className="card">
        <p>No years yet. Upload your first statements to start.</p>
      </div>
    )
  }

  return (
    <div className="stack">
      <div className="chips" role="tablist" aria-label="Year">
        {[...years.data].reverse().map((y) => (
          <a key={y} role="tab" aria-selected={y === shown} className={y === shown ? 'chip on' : 'chip'} href={href({ name: 'year', year: y })}>
            {y}
          </a>
        ))}
      </div>
      {load.error && <ErrorBox message={load.error} retry={load.reload} />}
      {!load.data && !load.error && <Loading />}
      {load.data && (
        <>
          <section className="card summary-card">
            <div className="eyebrow">{shown === now ? `${shown} so far` : shown}</div>
            <Totals earnings={load.data.summary.earnings} spendings={load.data.summary.spendings} trips={load.data.summary.trips} final={load.data.summary.final} />
            {load.data.summary.months.length > 0 && (
              <>
                <h3>Final by month</h3>
                <MonthBars months={load.data.summary.months} />
              </>
            )}
          </section>

          <section className="card flush">
            <h3 className="list-title">Months</h3>
            <table className="year-table pad-x">
              <thead>
                <tr>
                  <th>Month</th>
                  <th>Earnings</th>
                  <th>Spending</th>
                  <th>Trips</th>
                  <th>Final</th>
                </tr>
              </thead>
              <tbody>
                {[...load.data.summary.months].reverse().map((m) => (
                  <tr key={m.month}>
                    <td>
                      <a href={href({ name: 'month', year: shown, month: m.month })}>{monthName(shown!, m.month).slice(0, 3)}</a>
                    </td>
                    <td>{num(m.earnings)}</td>
                    <td>{num(m.spendings)}</td>
                    <td className={m.trips < 0 ? 'neg' : ''}>{num(m.trips)}</td>
                    <td className={m.final < 0 ? 'neg' : 'pos'}>{num(m.final)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {load.data.summary.byCategory.length > 0 && (
            <section className="card summary-card">
              <h3>By Category</h3>
              <Bars items={load.data.summary.byCategory} max={Math.max(1, ...load.data.summary.byCategory.map((c) => c.amount))} />
            </section>
          )}

          {load.data.trips.length > 0 && (
            <section className="card flush">
              <h3 className="list-title">Trips</h3>
              <ul className="rows">
                {load.data.trips.map(({ trip, total }) => (
                  <li key={trip.name}>
                    <a className="row" href={href({ name: 'trips', trip: trip.name })}>
                      <span className="row-main">
                        <span className="row-item">{trip.name}</span>
                        <span className="row-sub">
                          <span>
                            {shortDate(trip.start)} – {shortDate(trip.end)}
                          </span>
                        </span>
                      </span>
                      <span className={total !== null && total < 0 ? 'row-amt neg' : 'row-amt'}>{total === null ? '' : rm(total)}</span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <p className="muted small">Amounts in RM. Your own sheets that count in totals are included, as in the Year End Summary.</p>
        </>
      )}
    </div>
  )
}

const num = (n: number) => n.toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
