import { useState } from 'react'
import { useLoad } from '../app/context'
import { rm } from '../app/format'
import { useStored } from '../app/store'
import { Chips, Empty, ErrorBox, Loading } from '../components/ui'
import type { Kind, Row } from '../data/Backend'
import { EditRow, RowList } from './Month'

const KINDS = ['spend', 'earn'] as const
const SHOWN = 200 // enough for any real search; keeps the list quick on a phone

/** Find transactions in every year: words match item, category, remarks, source, trip, date; a number matches the amount. */
export function Search() {
  const load = useLoad((b) => b.allRows())
  // Kept while you look at a result and come back.
  const [q, setQ] = useStored('search.q', '')
  const [kind, setKind] = useStored<Kind | ''>('search.kind', '')
  const [editing, setEditing] = useState<Row>()

  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  const hits = (load.data ?? []).filter((r) => {
    if (kind && r.kind !== kind) return false
    if (!words.length) return false
    const text = [r.item, r.category, r.importance, r.remarks, r.source, r.trip ?? '', r.date].join(' ').toLowerCase()
    const amount = r.amount.toFixed(2)
    return words.every((w) => {
      const n = w.replace(/^rm/, '').replace(/,/g, '')
      if (/^\d+(\.\d+)?$/.test(n)) return amount.startsWith(n) || amount === Number(n).toFixed(2) || text.includes(w)
      return text.includes(w)
    })
  })
  // Newest first, across years (RowList sorts by date within what it's given).
  const shown = [...hits].sort((a, b) => b.date.localeCompare(a.date)).slice(0, SHOWN)
  const spent = hits.filter((r) => r.kind === 'spend').reduce((a, r) => a + r.amount, 0)
  const earned = hits.filter((r) => r.kind === 'earn').reduce((a, r) => a + r.amount, 0)

  return (
    <div className="stack">
      <div className="card stack tight search-box">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. grab, food, toll, 45.50"
          aria-label="Search transactions"
          autoFocus
          enterKeyHint="search"
        />
        <Chips label="Kind" options={KINDS} value={kind} onChange={setKind} names={{ spend: 'Spending', earn: 'Earnings' }} />
      </div>
      {load.error && <ErrorBox message={load.error} retry={load.reload} />}
      {!load.data && !load.error && <Loading />}
      {load.data && !words.length && (
        <p className="muted">Type a shop, category, note, bank or amount. Searches all {load.data.length} transactions, every year.</p>
      )}
      {load.data && words.length > 0 && hits.length === 0 && (
        <Empty title="Nothing found">Try fewer words, or another spelling.</Empty>
      )}
      {hits.length > 0 && (
        <>
          <p className="small muted" aria-live="polite">
            {hits.length} found · spent {rm(spent)} · earned {rm(earned)}
            {hits.length > SHOWN && ` · showing the newest ${SHOWN}`}
          </p>
          <RowList title="Results" rows={shown} onTap={setEditing} withYear />
        </>
      )}
      {editing && <EditRow row={editing} onClose={() => setEditing(undefined)} />}
    </div>
  )
}
