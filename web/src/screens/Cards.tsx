import { useEffect, useState } from 'react'
import { errorText, useData, useLoad } from '../app/context'
import { shortDate, signedRm } from '../app/format'
import { href } from '../app/router'
import { CategoryPicker } from '../components/CategoryPicker'
import { Chips, Empty, ErrorBox, Field, Loading } from '../components/ui'
import { IMPORTANCE, type Card, type Category, type Importance } from '../data/Backend'

export function Cards() {
  const load = useLoad((b) => b.listCards())
  // Cards passed with "Later" in this visit; they stay open for next time.
  const [passed, setPassed] = useState<string[]>([])

  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />

  const cards = load.data
  const left = cards.filter((c) => !passed.includes(c.key))
  const card = left[0]

  if (!card) {
    return cards.length === 0 ? (
      <Empty title="All caught up">
        <p>Every recorded row has what it needs.</p>
        <a className="btn" href={href({ name: 'home' })}>
          Home
        </a>
      </Empty>
    ) : (
      <Empty title="That's all for now">
        <p>
          {cards.length} {cards.length === 1 ? 'card is' : 'cards are'} left for later. They stay in the To Update tab
          and come back next time.
        </p>
        <div className="btn-row center">
          <button className="btn" onClick={() => setPassed([])}>
            Go through them again
          </button>
          <a className="btn primary" href={href({ name: 'home' })}>
            Home
          </a>
        </div>
      </Empty>
    )
  }

  const n = cards.length - left.length + 1
  return (
    <div className="stack">
      <div className="progress" aria-label={`Card ${n} of ${cards.length}`}>
        <span>
          {n} of {cards.length}
        </span>
        <div className="bar">
          <div style={{ width: `${((n - 1) / cards.length) * 100}%` }} />
        </div>
      </div>
      <CardForm key={card.key} card={card} onLater={() => setPassed((p) => [...p, card.key])} />
    </div>
  )
}

function CardForm({ card, onLater }: { card: Card; onLater(): void }) {
  const { backend, changed, toast } = useData()
  const needsPurpose = card.needs.includes('purpose')
  const needsCategory = card.needs.includes('category')
  const isSpend = card.kind === 'spend'

  const [item, setItem] = useState('')
  const [category, setCategory] = useState<Category | ''>(card.category)
  const [importance, setImportance] = useState<Importance | ''>(card.importance)
  const [same, setSame] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [suggested, setSuggested] = useState<Category[]>([])

  // Suggestions from your past rows and the shop name; they follow what you type.
  useEffect(() => {
    if (!needsCategory || !isSpend) return
    let live = true
    const t = setTimeout(() => {
      backend.suggestCategories(card.key, item.trim()).then((c) => live && setSuggested(c), () => {})
    }, item ? 300 : 0)
    return () => {
      live = false
      clearTimeout(t)
    }
  }, [backend, card.key, item, needsCategory, isSpend])

  const who = card.remarks ? card.remarks.replace(/^(To|From) /, '') : card.statement
  const direction = card.counterparty ? (isSpend ? 'to' : 'from') : 'at'
  const complete = (!needsPurpose || item.trim() !== '') && (!needsCategory || category !== '')

  async function act(what: 'save' | 'later' | 'notmine') {
    setBusy(true)
    setError(undefined)
    try {
      if (what === 'save') {
        await backend.saveCard(card.key, {
          item: needsPurpose ? item.trim() : undefined,
          category: isSpend ? category : undefined,
          importance: isSpend ? importance : undefined,
          sameForEvery: same,
        })
        toast(same ? `Saved, and added a rule for ${who}` : 'Saved')
      } else if (what === 'later') {
        await backend.skipCard(card.key)
        onLater()
      } else {
        await backend.notMine(card.key)
        toast('Removed: not yours')
      }
      changed()
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  return (
    <form
      className="card update-card"
      onSubmit={(e) => {
        e.preventDefault()
        if (complete) act('save')
      }}
    >
      <div className="uc-top">
        <span className="muted">{shortDate(card.date)}</span>
        <span className="pill">{card.source}</span>
      </div>
      <div className={isSpend ? 'uc-amount neg' : 'uc-amount pos'}>{signedRm(card.amount, card.kind)}</div>
      {card.remarks && <div className="uc-who">{card.remarks}</div>}
      <dl className="uc-meta">
        <dt>Statement</dt>
        <dd className="mono">{card.statement}</dd>
        <dt>Recorded as</dt>
        <dd>
          {card.item}
          {card.category && <span className="muted"> · {card.category}</span>}
          {card.trip && <span className="muted"> · {card.trip}</span>}
        </dd>
      </dl>

      {needsPurpose && (
        <Field label="What was it for?">
          <input
            value={item}
            onChange={(e) => setItem(e.target.value)}
            placeholder={isSpend ? 'e.g. Lunch, Concert tickets' : 'e.g. Paid back for dinner'}
            autoFocus
            enterKeyHint="done"
          />
        </Field>
      )}
      {needsCategory && isSpend && (
        <Field label="Category">
          <CategoryPicker value={category} onChange={setCategory} suggested={suggested} />
        </Field>
      )}
      {isSpend && (
        <Field label="Importance" hint="Optional">
          <Chips label="Importance" options={IMPORTANCE} value={importance} onChange={setImportance} />
        </Field>
      )}

      <label className="toggle">
        <input type="checkbox" checked={same} onChange={(e) => setSame(e.target.checked)} disabled={!complete} />
        <span className="switch" aria-hidden />
        <span>
          Same for every payment {direction} <strong>{who}</strong> from now on
        </span>
      </label>

      {error && <p className="error-text">{error}</p>}

      <div className="uc-actions">
        <button type="button" className="btn ghost danger" disabled={busy} onClick={() => act('notmine')}>
          Not mine
        </button>
        <button type="button" className="btn" disabled={busy} onClick={() => act('later')}>
          Later
        </button>
        <button className="btn primary" disabled={busy || !complete}>
          Save
        </button>
      </div>
    </form>
  )
}
