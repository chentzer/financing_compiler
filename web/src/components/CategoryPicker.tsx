import { useState } from 'react'
import { errorText, useData, useLoad } from '../app/context'
import type { Category } from '../data/Backend'

/**
 * Your categories as chips, with suggestions first and "+ New" to add one
 * to your list (Settings › Lists) without leaving the form.
 */
export function CategoryPicker({
  value,
  onChange,
  suggested = [],
}: {
  value: Category | ''
  onChange(v: Category | ''): void
  suggested?: Category[]
}) {
  const { backend, toast } = useData()
  const load = useLoad((b) => b.listCategories())
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  const cats = load.data ?? []
  const picks = suggested.filter((c) => cats.includes(c))
  const rest = cats.filter((c) => !picks.includes(c))

  async function add() {
    const n = name.trim()
    if (!n) return
    const existing = cats.find((c) => c.toLowerCase() === n.toLowerCase())
    if (existing) {
      onChange(existing)
    } else {
      setBusy(true)
      try {
        await backend.saveCategories([...cats, n])
        load.reload()
        onChange(n)
        toast(`Added category "${n}"`)
      } catch (e) {
        toast(errorText(e))
        setBusy(false)
        return
      }
      setBusy(false)
    }
    setName('')
    setAdding(false)
  }

  const chip = (c: string, hint = false) => (
    <button
      key={c}
      type="button"
      role="radio"
      aria-checked={value === c}
      className={['chip', value === c && 'on', hint && 'suggested'].filter(Boolean).join(' ')}
      onClick={() => onChange(value === c ? '' : c)}
    >
      {hint && <span aria-hidden>✦ </span>}
      {c}
    </button>
  )

  return (
    <div className="category-picker">
      {picks.length > 0 && (
        <div className="chips" role="radiogroup" aria-label="Suggested categories">
          <span className="chips-label">Suggested</span>
          {picks.map((c) => chip(c, true))}
        </div>
      )}
      <div className="chips" role="radiogroup" aria-label="Category">
        {rest.map((c) => chip(c))}
        {!adding && (
          <button type="button" className="chip add" onClick={() => setAdding(true)} disabled={!load.data}>
            + New
          </button>
        )}
      </div>
      {adding && (
        <div className="add-category">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault() // don't submit the card
                add()
              } else if (e.key === 'Escape') {
                e.stopPropagation()
                setAdding(false)
              }
            }}
            placeholder="New category, e.g. Pets"
            aria-label="New category name"
            autoFocus
            enterKeyHint="done"
          />
          <button type="button" className="btn primary" disabled={busy || !name.trim()} onClick={add}>
            Add
          </button>
          <button type="button" className="btn ghost" disabled={busy} onClick={() => setAdding(false)}>
            Cancel
          </button>
        </div>
      )}
    </div>
  )
}
