import { useLoad } from '../app/context'
import { monthName, rm } from '../app/format'
import { href } from '../app/router'
import { ErrorBox, Loading } from '../components/ui'

export function Home() {
  const load = useLoad(async (b) => {
    const [months, cards] = await Promise.all([b.listMonths(), b.listCards()])
    const now = new Date()
    const current =
      months.find((m) => m.year === now.getFullYear() && m.month === now.getMonth() + 1) ?? months.at(-1)
    const summary = current ? await b.monthSummary(current.year, current.month) : undefined
    return { summary, cards: cards.length }
  })

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
    </div>
  )
}
