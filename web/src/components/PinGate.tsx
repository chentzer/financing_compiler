import { useState, type ReactNode } from 'react'
import { errorText, useData, useLoad } from '../app/context'
import type { VaultState } from '../data/Backend'
import { ErrorBox, Field, Loading } from './ui'

/**
 * Shows `children` once the saved statement passwords are unlocked.
 * Otherwise asks for the PIN (or to create one, the first time).
 */
export function PinGate({ children, reason }: { children: ReactNode; reason: string }) {
  const { backend, changed } = useData()
  const load = useLoad((b) => b.vaultState())
  const [pin, setPin] = useState('')
  const [again, setAgain] = useState('')
  const [rememberHere, setRememberHere] = useState(true)
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  if (load.error) return <ErrorBox message={load.error} retry={load.reload} />
  if (!load.data) return <Loading what="Checking your saved passwords" />
  if (load.data === 'unlocked') return <>{children}</>
  const state: VaultState = load.data
  const creating = state === 'new'
  const mismatch = creating && again.length > 0 && again !== pin
  const canSubmit = creating ? pin.length >= 6 && again === pin : pin.length > 0

  return (
    <form
      className="card stack pin-gate"
      onSubmit={async (e) => {
        e.preventDefault()
        if (!canSubmit) return
        setBusy(true)
        setError(undefined)
        try {
          if (creating) await backend.setVaultPin(pin, rememberHere)
          else await backend.unlockVault(pin, rememberHere)
          setPin('')
          setAgain('')
          changed()
        } catch (err) {
          setError(errorText(err))
        } finally {
          setBusy(false)
        }
      }}
    >
      <h3>{creating ? 'Create a PIN for your statement passwords' : 'Enter your PIN'}</h3>
      <p className="small muted">
        {creating
          ? `${reason} Your statement passwords are encrypted with this PIN (salted, 600,000 rounds) before they're saved to your Drive, so only the encrypted version leaves this device. Use 6 or more digits, or a passphrase. It can't be recovered: if you forget it, you set a new one and type your statement passwords again.`
          : `${reason} Your saved statement passwords are encrypted. Enter your PIN to use them on this device.`}
      </p>
      <Field label={creating ? 'New PIN' : 'PIN'}>
        <div className="pw-row">
          <input
            type={show ? 'text' : 'password'}
            inputMode="numeric"
            autoComplete={creating ? 'new-password' : 'current-password'}
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            autoFocus
          />
          <button type="button" className="btn ghost" onClick={() => setShow((s) => !s)}>
            {show ? 'Hide' : 'Show'}
          </button>
        </div>
      </Field>
      {creating && (
        <Field label="Type it again" hint={mismatch ? "The two PINs don't match." : undefined}>
          <input
            type={show ? 'text' : 'password'}
            inputMode="numeric"
            autoComplete="new-password"
            value={again}
            onChange={(e) => setAgain(e.target.value)}
          />
        </Field>
      )}
      <label className="check">
        <input type="checkbox" checked={rememberHere} onChange={(e) => setRememberHere(e.target.checked)} />
        Remember on this device (don't ask again here)
      </label>
      {error && <p className="error-text">{error}</p>}
      <div className="btn-row">
        <button className="btn primary" disabled={busy || !canSubmit}>
          {busy ? (creating ? 'Encrypting…' : 'Unlocking…') : creating ? 'Create PIN' : 'Unlock'}
        </button>
      </div>
    </form>
  )
}
