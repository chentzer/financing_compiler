import { useLoad } from '../app/context'
import { monthName, rm } from '../app/format'
import { href } from '../app/router'
import type { YearSummary } from '../data/Backend'
import { ErrorBox, Loading } from '../components/ui'
import { Bars } from './Month'

export function Home() {
  const load = useLoad(async (b) => {
    const [months, cards] = await Promise.all([b.listMonths(), b.listCards()])
    const now = new Date()
    const current =
      months.find((m) => m.year === now.getFullYear() && m.month === now.getMonth() + 1) ?? months.at(-1)
    const summary = current ? await b.monthSummary(current.year, current.month) : undefined
    return { summary, cards: cards.length }
  })
  // Every year, for this year's card and the to-date one (2 reads a year).
  const years = useLoad(async (b) => Promise.all((await b.listYears()).map((y) => b.yearSummary(y))))

  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />
  const { summary, cards } = load.data

  return (
    <div className="stack">
      {summary ? (
        <a className="card summary-card" href={href({ name: 'month', year: summary.year, month: summary.month })}>
          <div className="eyebrow">{monthName(summary.year, summary.month)}</div>
          <div className="final">
            <span className="label">Final</span>
            <span className={summary.final < 0 ? 'amount neg' : 'amount pos'}>{rm(summary.final)}</span>
          </div>
          <div className="pair">
            <div>
              <span className="label">Spending</span>
              <span className="amount">{rm(summary.spendings)}</span>
            </div>
            <div>
              <span className="label">Earnings</span>
              <span className="amount">{rm(summary.earnings)}</span>
            </div>
          </div>
          {summary.tripsTotal > 0 && <div className="muted small">Trips this month: {rm(summary.tripsTotal)}</div>}
          <span className="link-hint">See month →</span>
        </a>
      ) : (
        <div className="card">
          <p>No months yet. Upload your first statements to start.</p>
        </div>
      )}

      <div className="actions-row">
        <a className={cards ? 'btn big primary' : 'btn big'} href={href({ name: 'cards' })}>
          <span className="big-num">{cards}</span>
          <span>to update</span>
        </a>
        <a className="btn big" href={href({ name: 'upload' })}>
          <span className="big-icon" aria-hidden>
            ⇪
          </span>
          <span>Upload statements</span>
        </a>
      </div>

      {years.error && <ErrorBox message={years.error} retry={years.reload} />}
      {!years.data && !years.error && <Loading />}
      {years.data && years.data.length > 0 && <YearCards years={years.data} />}
    </div>
  )
}

function YearCards({ years }: { years: YearSummary[] }) {
  const now = new Date().getFullYear()
  const year = years.find((y) => y.year === now) ?? years.at(-1)!
  const sum = (k: 'earnings' | 'spendings' | 'trips' | 'final') => years.reduce((a, y) => a + y[k], 0)
  const first = years[0].year
  return (
    <>
      <section className="card summary-card">
        <div className="eyebrow">{year.year === now ? `${year.year} so far` : year.year}</div>
        <Totals earnings={year.earnings} spendings={year.spendings} trips={year.trips} final={year.final} />
        {year.months.length > 0 && (
          <>
            <h3>Final by month</h3>
            <MonthBars months={year.months} />
          </>
        )}
        {year.byCategory.length > 0 && (
          <>
            <h3>By Category</h3>
            <Bars items={year.byCategory} max={Math.max(1, ...year.byCategory.map((c) => c.amount))} />
          </>
        )}
      </section>

      <section className="card summary-card">
        <div className="eyebrow">
          To date · {first === now ? now : `${first} – ${now}`}
        </div>
        <Totals earnings={sum('earnings')} spendings={sum('spendings')} trips={sum('trips')} final={sum('final')} />
        <table className="year-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Earnings</th>
              <th>Spending + trips</th>
              <th>Final</th>
            </tr>
          </thead>
          <tbody>
            {years.map((y) => (
              <tr key={y.year}>
                <td>{y.year}</td>
                <td>{num(y.earnings)}</td>
                <td>{num(y.spendings + y.trips)}</td>
                <td className={y.final < 0 ? 'neg' : 'pos'}>{num(y.final)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <a className="link-hint" href={href({ name: 'trips' })}>
          See trips →
        </a>
      </section>
    </>
  )
}

function Totals({ earnings, spendings, trips, final }: { earnings: number; spendings: number; trips: number; final: number }) {
  return (
    <>
      <div className="final">
        <span className="label">Final</span>
        <span className={final < 0 ? 'amount neg' : 'amount pos'}>{rm(final)}</span>
      </div>
      <div className="pair three">
        <div>
          <span className="label">Earnings</span>
          <span className="amount">{rm(earnings)}</span>
        </div>
        <div>
          <span className="label">Spending</span>
          <span className="amount">{rm(spendings)}</span>
        </div>
        <div>
          <span className="label">Trips</span>
          <span className="amount">{rm(trips)}</span>
        </div>
      </div>
    </>
  )
}

const num = (n: number) => n.toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Each month's Final as a bar: up for saved, down for overspent. */
function MonthBars({ months }: { months: YearSummary['months'] }) {
  const max = Math.max(1, ...months.map((m) => Math.abs(m.final)))
  return (
    <ul className="bars">
      {months.map((m) => (
        <li key={m.month} className={m.final === 0 ? 'zero' : ''}>
          <span className="bar-name">{SHORT[m.month - 1]}</span>
          <span className="bar-track">
            <span className={m.final < 0 ? 'bar-fill neg' : 'bar-fill'} style={{ width: `${(Math.abs(m.final) / max) * 100}%` }} />
          </span>
          <span className={m.final < 0 ? 'bar-amt neg' : 'bar-amt'}>{rm(m.final)}</span>
        </li>
      ))}
    </ul>
  )
}
