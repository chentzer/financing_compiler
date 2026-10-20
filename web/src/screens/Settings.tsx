import { useState, type ReactNode } from 'react'
import { PinGate } from '../components/PinGate'
import { errorText, useData, useLoad } from '../app/context'
import { shortDate } from '../app/format'
import { href } from '../app/router'
import { Chips, ErrorBox, Field, Loading, Sheet } from '../components/ui'
import {
  CATEGORIES,
  IMPORTANCE,
  STATEMENT_SOURCES,
  type Passwords,
  type Person,
  type Rule,
  type Settings as SettingsData,
  type Trip,
} from '../data/Backend'

const TABS = [
  { id: 'rules', label: 'Rules' },
  { id: 'people', label: 'People' },
  { id: 'trips', label: 'Trips' },
  { id: 'payees', label: 'Own payees' },
  { id: 'passwords', label: 'Passwords' },
]

export function Settings({ tab = 'rules', account }: { tab?: string; account: ReactNode }) {
  return (
    <div className="stack">
      {account}
      <nav className="tabs" aria-label="Settings sections">
        {TABS.map((t) => (
          <a key={t.id} href={href({ name: 'settings', tab: t.id })} className={t.id === tab ? 'tab on' : 'tab'} aria-current={t.id === tab ? 'page' : undefined}>
            {t.label}
          </a>
        ))}
      </nav>
      {tab === 'passwords' ? <PasswordsTab /> : <SettingsTab tab={tab} />}
    </div>
  )
}

/** Rules / People / Trips / Own payees: edit a copy, save the whole Settings sheet. */
function SettingsTab({ tab }: { tab: string }) {
  const { backend, changed, toast } = useData()
  const load = useLoad((b) => b.getSettings())
  const [editing, setEditing] = useState<{ index: number } | null>(null)

  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />
  const s = load.data

  async function save(next: SettingsData, message = 'Settings saved') {
    try {
      await backend.saveSettings(next)
      toast(message)
      changed()
      setEditing(null)
    } catch (e) {
      toast(errorText(e))
    }
  }

  const close = () => setEditing(null)
  const replace = <T,>(list: T[], i: number, v: T | null): T[] =>
    v === null ? list.filter((_, j) => j !== i) : i < 0 ? [...list, v] : list.map((x, j) => (j === i ? v : x))

  if (tab === 'people') {
    return (
      <>
        <ListCard
          intro="How people's names show in Remarks. Names not listed are shortened automatically."
          items={s.people.map((p) => ({ title: p.shownAs, sub: p.statementName }))}
          onEdit={(index) => setEditing({ index })}
          addLabel="Add person"
        />
        {editing && (
          <PersonSheet
            person={s.people[editing.index]}
            onClose={close}
            onSave={(p) => save({ ...s, people: replace(s.people, editing.index, p) })}
          />
        )}
      </>
    )
  }
  if (tab === 'trips') {
    return (
      <>
        <ListCard
          intro="Each trip gets its own tab. Its total comes off the Final of the month it ends."
          items={s.trips.map((t) => ({
            title: t.name,
            sub: `${shortDate(t.start)} – ${shortDate(t.end)}${t.currency ? ` · ${t.currency}` : ''}`,
          }))}
          onEdit={(index) => setEditing({ index })}
          addLabel="Add trip"
        />
        {editing && (
          <TripSheet
            trip={s.trips[editing.index]}
            onClose={close}
            onSave={(t) => save({ ...s, trips: replace(s.trips, editing.index, t) })}
          />
        )}
      </>
    )
  }
  if (tab === 'payees') {
    return (
      <>
        <ListCard
          intro="Paying these is your own money moving (card bills, investments), not spending."
          items={s.ownPayees.map((p) => ({ title: p }))}
          onEdit={(index) => setEditing({ index })}
          addLabel="Add payee"
        />
        {editing && (
          <TextSheet
            title="Own payee"
            label="Payee as on the statement"
            value={s.ownPayees[editing.index]}
            onClose={close}
            onSave={(v) => save({ ...s, ownPayees: replace(s.ownPayees, editing.index, v) })}
          />
        )}
      </>
    )
  }
  return (
    <>
      <ListCard
        intro="First match wins. A rule fills in Item, Category and Importance for statement lines containing its text."
        items={s.rules.map((r) => ({
          title: r.match,
          sub: r.skip
            ? 'Left out'
            : [r.item && `→ ${r.item}`, r.category, r.importance, r.trip, r.source && `only ${r.source}`].filter(Boolean).join(' · ') ||
              'No effect yet',
        }))}
        onEdit={(index) => setEditing({ index })}
        addLabel="Add rule"
      />
      {editing && (
        <RuleSheet
          rule={s.rules[editing.index]}
          trips={s.trips.map((t) => t.name)}
          onClose={close}
          onSave={(r) => save({ ...s, rules: replace(s.rules, editing.index, r) })}
        />
      )}
    </>
  )
}

function ListCard({
  intro,
  items,
  onEdit,
  addLabel,
}: {
  intro: string
  items: { title: string; sub?: string }[]
  onEdit(index: number): void
  addLabel: string
}) {
  return (
    <section className="card flush">
      <p className="muted small pad">{intro}</p>
      <ul className="rows">
        {items.map((it, i) => (
          <li key={i}>
            <button className="row" onClick={() => onEdit(i)}>
              <span className="row-main">
                <span className="row-item">{it.title}</span>
                {it.sub && <span className="row-sub">{it.sub}</span>}
              </span>
              <span className="chev" aria-hidden>
                ›
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div className="pad">
        <button className="btn" onClick={() => onEdit(-1)}>
          + {addLabel}
        </button>
      </div>
    </section>
  )
}

function SheetButtons({ isNew, onDelete, onClose, canSave }: { isNew: boolean; onDelete(): void; onClose(): void; canSave: boolean }) {
  return (
    <div className="btn-row end">
      {!isNew && (
        <button type="button" className="btn ghost danger push-left" onClick={onDelete}>
          Delete
        </button>
      )}
      <button type="button" className="btn" onClick={onClose}>
        Cancel
      </button>
      <button className="btn primary" disabled={!canSave}>
        Save
      </button>
    </div>
  )
}

type SaveFn<T> = (v: T | null) => void

function RuleSheet({ rule, trips, onClose, onSave }: { rule?: Rule; trips: string[]; onClose(): void; onSave: SaveFn<Rule> }) {
  const [r, setR] = useState<Rule>(rule ?? { match: '' })
  return (
    <Sheet title={rule ? 'Edit rule' : 'New rule'} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          onSave(clean({ ...r, match: r.match.trim() }))
        }}
      >
        <Field label="Statement contains" hint="Case doesn't matter, e.g. GRAB*FOOD">
          <input value={r.match} onChange={(e) => setR({ ...r, match: e.target.value })} autoFocus={!rule} />
        </Field>
        <Field label="Only for">
          <select value={r.source ?? ''} onChange={(e) => setR({ ...r, source: e.target.value })}>
            <option value="">Any bank or wallet</option>
            {STATEMENT_SOURCES.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        <label className="toggle">
          <input type="checkbox" checked={!!r.skip} onChange={(e) => setR({ ...r, skip: e.target.checked })} />
          <span className="switch" aria-hidden />
          <span>Leave these out (not recorded)</span>
        </label>
        {!r.skip && (
          <>
            <Field label="Item" hint="Blank keeps the shop name">
              <input value={r.item ?? ''} onChange={(e) => setR({ ...r, item: e.target.value })} />
            </Field>
            <Field label="Category">
              <Chips label="Category" options={CATEGORIES} value={r.category ?? ''} onChange={(v) => setR({ ...r, category: v })} />
            </Field>
            <Field label="Importance">
              <Chips label="Importance" options={IMPORTANCE} value={r.importance ?? ''} onChange={(v) => setR({ ...r, importance: v })} />
            </Field>
            {trips.length > 0 && (
              <Field label="Send to trip">
                <select value={r.trip ?? ''} onChange={(e) => setR({ ...r, trip: e.target.value })}>
                  <option value="">No</option>
                  {trips.map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </Field>
            )}
          </>
        )}
        <SheetButtons isNew={!rule} onDelete={() => onSave(null)} onClose={onClose} canSave={r.match.trim() !== ''} />
      </form>
    </Sheet>
  )
}

function PersonSheet({ person, onClose, onSave }: { person?: Person; onClose(): void; onSave: SaveFn<Person> }) {
  const [p, setP] = useState<Person>(person ?? { statementName: '', shownAs: '' })
  return (
    <Sheet title={person ? 'Edit person' : 'New person'} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          onSave({ statementName: p.statementName.trim(), shownAs: p.shownAs.trim() })
        }}
      >
        <Field label="Name on the statement" hint="e.g. TAN MEI JANE">
          <input value={p.statementName} onChange={(e) => setP({ ...p, statementName: e.target.value })} autoFocus={!person} />
        </Field>
        <Field label="Show as">
          <input value={p.shownAs} onChange={(e) => setP({ ...p, shownAs: e.target.value })} />
        </Field>
        <SheetButtons isNew={!person} onDelete={() => onSave(null)} onClose={onClose} canSave={!!p.statementName.trim() && !!p.shownAs.trim()} />
      </form>
    </Sheet>
  )
}

function TripSheet({ trip, onClose, onSave }: { trip?: Trip; onClose(): void; onSave: SaveFn<Trip> }) {
  const [t, setT] = useState<Trip>(trip ?? { name: '', start: '', end: '', match: [] })
  const [match, setMatch] = useState((trip?.match ?? []).join(', '))
  const valid = t.name.trim() && t.start && t.end && t.start <= t.end
  return (
    <Sheet title={trip ? 'Edit trip' : 'New trip'} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          onSave(
            clean({
              ...t,
              name: t.name.trim(),
              match: match.split(',').map((m) => m.trim()).filter(Boolean),
            }),
          )
        }}
      >
        <Field label="Name">
          <input value={t.name} onChange={(e) => setT({ ...t, name: e.target.value })} placeholder="e.g. Japan Trip" autoFocus={!trip} />
        </Field>
        <div className="two">
          <Field label="Start">
            <input type="date" value={t.start} onChange={(e) => setT({ ...t, start: e.target.value })} />
          </Field>
          <Field label="End">
            <input type="date" value={t.end} onChange={(e) => setT({ ...t, end: e.target.value })} />
          </Field>
        </div>
        <div className="two">
          <Field label="Currency" hint="Blank for local trips">
            <input value={t.currency ?? ''} onChange={(e) => setT({ ...t, currency: e.target.value })} placeholder="e.g. Yen" />
          </Field>
          <Field label="RM per 1 unit" hint="Blank = from Money Exchange rows">
            <input
              type="number"
              inputMode="decimal"
              step="any"
              value={t.rate ?? ''}
              onChange={(e) => setT({ ...t, rate: e.target.value ? Number(e.target.value) : undefined })}
            />
          </Field>
        </div>
        <Field label="Earlier bookings containing" hint="Comma-separated, e.g. AIRASIA, AGODA">
          <input value={match} onChange={(e) => setMatch(e.target.value)} />
        </Field>
        <Field label="Itinerary link">
          <input type="url" value={t.link ?? ''} onChange={(e) => setT({ ...t, link: e.target.value })} />
        </Field>
        <SheetButtons isNew={!trip} onDelete={() => onSave(null)} onClose={onClose} canSave={!!valid} />
      </form>
    </Sheet>
  )
}

function TextSheet({
  title,
  label,
  value,
  onClose,
  onSave,
}: {
  title: string
  label: string
  value?: string
  onClose(): void
  onSave: SaveFn<string>
}) {
  const [v, setV] = useState(value ?? '')
  return (
    <Sheet title={title} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          onSave(v.trim())
        }}
      >
        <Field label={label}>
          <input value={v} onChange={(e) => setV(e.target.value)} autoFocus />
        </Field>
        <SheetButtons isNew={value === undefined} onDelete={() => onSave(null)} onClose={onClose} canSave={!!v.trim()} />
      </form>
    </Sheet>
  )
}

function PasswordsTab() {
  return (
    <PinGate reason="Statement passwords are kept encrypted.">
      <PasswordsList />
    </PinGate>
  )
}

function PasswordsList() {
  const { backend, changed, toast } = useData()
  const [changingPin, setChangingPin] = useState(false)
  const load = useLoad((b) => b.getPasswords())
  const [editing, setEditing] = useState<string | null>(null)

  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading />
  const pw = load.data

  async function save(next: Passwords, message: string) {
    try {
      await backend.savePasswords(next)
      toast(message)
      changed()
      setEditing(null)
    } catch (e) {
      toast(errorText(e))
    }
  }

  return (
    <section className="card flush">
      <p className="muted small pad">
        Encrypted with your PIN, then kept in your Google Drive's private app folder (never in a sheet). Used
        automatically when you upload.
      </p>
      <div className="btn-row pad">
        <button className="btn small" onClick={() => setChangingPin(true)}>
          Change PIN
        </button>
        <button
          className="btn small ghost"
          onClick={async () => {
            await backend.lockVault()
            toast('Locked on this device: the PIN will be asked next time')
            changed()
          }}
        >
          Lock on this device
        </button>
      </div>
      <ul className="rows">
        {STATEMENT_SOURCES.map((s) => (
          <li key={s.key} className="row static">
            <span className="row-main">
              <span className="row-item">{s.label}</span>
              <span className="row-sub mono">{pw[s.key] ? '•'.repeat(8) : 'Not set'}</span>
            </span>
            <span className="btn-row tight">
              <button className="btn small" onClick={() => setEditing(s.key)}>
                {pw[s.key] ? 'Change' : 'Set'}
              </button>
              {pw[s.key] && (
                <button
                  className="btn small ghost danger"
                  onClick={() => {
                    const { [s.key]: _gone, ...rest } = pw
                    void _gone
                    save(rest, `${s.label} password removed`)
                  }}
                >
                  Remove
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {changingPin && <ChangePinSheet onClose={() => setChangingPin(false)} />}
      {editing && (
        <PasswordSheet
          label={STATEMENT_SOURCES.find((s) => s.key === editing)!.label}
          onClose={() => setEditing(null)}
          onSave={(v) => save({ ...pw, [editing]: v }, 'Password saved')}
        />
      )}
    </section>
  )
}

function ChangePinSheet({ onClose }: { onClose(): void }) {
  const { backend, changed, toast } = useData()
  const [pin, setPin] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const ok = pin.length >= 6 && pin === again
  return (
    <Sheet title="Change PIN" onClose={onClose}>
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!ok) return
          setBusy(true)
          try {
            await backend.setVaultPin(pin, true)
            toast('PIN changed: passwords re-encrypted with a new salt')
            changed()
            onClose()
          } catch (err) {
            setError(errorText(err))
          } finally {
            setBusy(false)
          }
        }}
      >
        <p className="small muted">Your other devices will ask for the new PIN next time.</p>
        <Field label="New PIN" hint="6 or more digits, or a passphrase">
          <input type="password" inputMode="numeric" autoComplete="new-password" value={pin} onChange={(e) => setPin(e.target.value)} autoFocus />
        </Field>
        <Field label="Type it again" hint={again && again !== pin ? "The two PINs don't match." : undefined}>
          <input type="password" inputMode="numeric" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
        </Field>
        {error && <p className="error-text">{error}</p>}
        <div className="btn-row end">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy || !ok}>
            {busy ? 'Encrypting…' : 'Change PIN'}
          </button>
        </div>
      </form>
    </Sheet>
  )
}

function PasswordSheet({ label, onClose, onSave }: { label: string; onClose(): void; onSave(v: string): void }) {
  const [v, setV] = useState('')
  const [show, setShow] = useState(false)
  return (
    <Sheet title={`${label} password`} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          if (v) onSave(v)
        }}
      >
        <Field label="New password">
          <div className="pw-row">
            <input type={show ? 'text' : 'password'} value={v} onChange={(e) => setV(e.target.value)} autoComplete="off" autoFocus />
            <button type="button" className="btn ghost" onClick={() => setShow((s) => !s)}>
              {show ? 'Hide' : 'Show'}
            </button>
          </div>
        </Field>
        <div className="btn-row end">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={!v}>
            Save
          </button>
        </div>
      </form>
    </Sheet>
  )
}

/** Drop empty optional fields so the Settings sheet stays tidy. */
function clean<T extends object>(o: T): T {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== '' && v !== undefined && v !== false)) as T
}
