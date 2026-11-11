import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { go, type Route } from '../app/router'
import { setStored, useStored } from '../app/store'

/**
 * First-launch guided tour: one step per tab and feature, shown on the real
 * screen with a spotlight on the actual control. Runs once per device
 * (TOUR_KEY), can be skipped, and replays from Settings ("Replay the tour").
 *
 * Keep it current: when a tab or feature is added, moved or removed, change
 * STEPS in the same commit (CLAUDE.md, App UI rules).
 */
interface Step {
  /** Page to show for this step. */
  route: Route
  /** data-tour value of the control to spotlight; none = a centred card. */
  target?: string
  title: string
  text: string
}

const STEPS: Step[] = [
  { route: { name: 'home' }, title: 'Welcome to FinMerge',
    text: 'Your statements become monthly accounts in your own Google Sheets. This quick tour shows where everything is.' },
  { route: { name: 'home' }, target: 'tab-home', title: 'Home',
    text: 'This month, this year so far, and your totals to date.' },
  { route: { name: 'upload' }, target: 'tab-upload', title: 'Upload',
    text: 'Add bank and e-wallet statements (PDF), Splitwise exports or an old accounts workbook. On the app it keeps going if you switch apps.' },
  { route: { name: 'upload' }, target: 'upload-pick', title: 'Share to FinMerge',
    text: 'Or share a statement from your bank app or Files straight to FinMerge: it uploads by itself.' },
  { route: { name: 'cards' }, target: 'tab-cards', title: 'To Update',
    text: 'Transactions that still need a purpose or a category, one card at a time.' },
  { route: { name: 'cards' }, target: 'card-actions', title: 'Answer a card',
    text: 'Save, Skip, Not mine, or ✈ Trip to move it onto a trip. Each one shows Undo for a few seconds.' },
  { route: { name: 'month' }, target: 'tab-accounts', title: 'Accounts',
    text: 'Your spending and earnings, month by month.' },
  { route: { name: 'month' }, target: 'subtabs-accounts', title: 'Month, Year, Trips',
    text: 'Switch between a month, the whole year, and your trips here.' },
  { route: { name: 'month' }, target: 'month-nav', title: 'Pick a month',
    text: 'Use the arrows or the calendar to go to another month.' },
  { route: { name: 'month' }, target: 'date-filter', title: 'Filter by date',
    text: 'Pick a From and To date to see only those days, with their totals.' },
  { route: { name: 'month' }, target: 'row', title: 'Edit a transaction',
    text: 'Tap any transaction to change it, move it to a trip, or delete it.' },
  { route: { name: 'month' }, target: 'add-row', title: 'Add by hand',
    text: 'Add cash spending or anything a statement missed.' },
  { route: { name: 'trips' }, target: 'add-trip', title: 'Trips',
    text: 'Each trip has its own page and total. Add one here; open a trip to change its dates, currencies and rates.' },
  { route: { name: 'investments' }, target: 'tab-sheets', title: 'Sheets',
    text: 'Your investments, and sheets of your own like ang pao.' },
  { route: { name: 'home' }, target: 'search', title: 'Search',
    text: 'Find any transaction by name, category, note, bank or amount, across every year.' },
  { route: { name: 'home' }, target: 'settings', title: 'Settings',
    text: 'Rules, categories and passwords. You can replay this tour from here.' },
]

const TOUR_KEY = 'fincomp.tour.v1'
const PAD = 6

function tourDone(): boolean {
  try {
    return localStorage.getItem(TOUR_KEY) === 'done'
  } catch {
    return true // storage blocked: don't show it on every visit
  }
}

function markDone(): void {
  try {
    localStorage.setItem(TOUR_KEY, 'done')
  } catch {
    /* storage blocked */
  }
}

/** Start the tour (Settings › Replay the tour). */
export function startTour(): void {
  setStored('tour.step', 0)
}

/** The visible element for a data-tour name (side nav or bottom nav, whichever is showing). */
function findTarget(name: string): HTMLElement | null {
  for (const el of document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`)) {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden') return el
  }
  return null
}

/** The spotlight around a control, kept inside the screen (bottom tabs sit at its very edge). */
function holeStyle(r: DOMRect) {
  const top = Math.max(2, r.top - PAD)
  const left = Math.max(2, r.left - PAD)
  const bottom = Math.min(window.innerHeight - 2, r.bottom + PAD)
  const right = Math.min(window.innerWidth - 2, r.right + PAD)
  return { top, left, width: right - left, height: bottom - top }
}

export function Tour() {
  const [step, setStep] = useStored<number | null>('tour.step', tourDone() ? null : 0)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const [missing, setMissing] = useState(false)
  const card = useRef<HTMLDivElement>(null)
  const [cardPos, setCardPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 })
  const s = step === null ? null : STEPS[step]

  const close = useCallback(() => {
    markDone()
    setStep(null)
  }, [setStep])

  // Go to the step's page, then find its control (the page may still be loading).
  useEffect(() => {
    if (!s) return
    go(s.route)
    setRect(null)
    setMissing(false)
    if (!s.target) return
    let tries = 0
    let timer = 0
    const look = () => {
      const el = findTarget(s.target!)
      if (el) {
        // Bring it into the upper part of the screen, leaving room for the card below it.
        // Controls in the bars (bottom tabs, header) are always in view: don't scroll for those.
        const r = el.getBoundingClientRect()
        if (!el.closest('.bottom-nav, .topbar, .side') && (r.top < 0 || r.bottom > window.innerHeight * 0.55)) {
          // Tall controls (large text) go nearer the top so the card still fits under them.
          const roomForCard = card.current?.offsetHeight ?? 220
          const at = Math.max(12, Math.min(window.innerHeight * 0.18, window.innerHeight - r.height - roomForCard - 40))
          window.scrollBy({ top: r.top - at })
        }
        timer = window.setTimeout(() => setRect(el.getBoundingClientRect()), 120)
      } else if (tries++ < 30) {
        timer = window.setTimeout(look, 100)
      } else {
        setMissing(true) // e.g. no cards to answer: explain it without a spotlight
      }
    }
    look()
    return () => clearTimeout(timer)
  }, [s])

  // Keep the spotlight on its control when the window changes.
  useEffect(() => {
    if (!s?.target) return
    const update = () => {
      const el = findTarget(s.target!)
      if (el) setRect(el.getBoundingClientRect())
    }
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, { passive: true })
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update)
    }
  }, [s])

  // Card below the control when there's room, else above; always on screen.
  useLayoutEffect(() => {
    const c = card.current
    if (!c || !s) return
    const vw = window.innerWidth
    const vh = window.innerHeight
    const h = c.offsetHeight
    const w = c.offsetWidth
    if (!rect) {
      setCardPos({ top: Math.max(8, (vh - h) / 2), left: Math.max(8, (vw - w) / 2) })
      return
    }
    const below = rect.bottom + PAD + 12
    const above = rect.top - PAD - 12 - h
    const top = below + h <= vh - 8 ? below : above >= 8 ? above : Math.max(8, vh - h - 8)
    const left = Math.min(Math.max(8, rect.left + rect.width / 2 - w / 2), vw - w - 8)
    setCardPos({ top, left })
  }, [rect, s, step])

  // Keyboard: arrows move, Escape skips; focus goes to the card.
  useEffect(() => {
    if (step === null) return
    card.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
      if (e.key === 'ArrowRight') setStep((n) => (n === null ? n : Math.min(n + 1, STEPS.length - 1)))
      if (e.key === 'ArrowLeft') setStep((n) => (n === null ? n : Math.max(n - 1, 0)))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [step, close, setStep])

  if (!s || step === null) return null
  const last = step === STEPS.length - 1
  const spot = s.target && rect && !missing

  return (
    <div className="tour" role="presentation">
      {spot ? (
        <div className="tour-hole" style={holeStyle(rect)} />
      ) : (
        <div className="tour-dim" />
      )}
      <div
        ref={card}
        className="tour-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-text"
        tabIndex={-1}
        style={cardPos}
      >
        <div className="tour-progress" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
          {step + 1} of {STEPS.length}
        </div>
        <h2 id="tour-title">{s.title}</h2>
        <p id="tour-text">
          {s.text}
          {missing && s.target === 'card-actions' && ' (No cards right now: they appear after an upload.)'}
        </p>
        <div className="tour-buttons">
          <button type="button" className="btn ghost" onClick={close}>
            Skip
          </button>
          <span className="grow" />
          {step > 0 && (
            <button type="button" className="btn" onClick={() => setStep(step - 1)}>
              Back
            </button>
          )}
          <button type="button" className="btn primary" onClick={() => (last ? close() : setStep(step + 1))}>
            {last ? 'Done' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
