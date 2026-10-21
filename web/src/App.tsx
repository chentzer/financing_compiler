import { useEffect, useMemo, useState } from 'react'
import type { Auth, User } from './auth/Auth'
import { DataProvider, errorText, useLoad } from './app/context'
import { href, useRoute, type Route } from './app/router'
import { createBackend } from './setup'
import { Cards } from './screens/Cards'
import { Home } from './screens/Home'
import { Month } from './screens/Month'
import { Settings } from './screens/Settings'
import { Sheets } from './screens/Sheets'
import { Trips } from './screens/Trips'
import { Year } from './screens/Year'
import { listenForShares } from './app/share'
import { useStored } from './app/store'
import type { UploadProgress } from './data/Backend'
import { Upload } from './screens/Upload'

const TITLES: Record<Route['name'], string> = {
  home: 'FinMerge',
  upload: 'Upload',
  cards: 'To Update',
  month: 'Month',
  year: 'Year',
  trips: 'Trips',
  investments: 'Investments',
  sheets: 'Sheets',
  settings: 'Settings',
}

export default function App({ auth }: { auth: Auth }) {
  const [user, setUser] = useState<User | null>(() => auth.currentUser())
  const backend = useMemo(() => (user ? createBackend(auth) : null), [auth, user])
  const [reconnect, setReconnect] = useState(false)
  useEffect(() => auth.onReconnectNeeded?.(setReconnect), [auth])

  if (!user || !backend) return <SignIn auth={auth} onSignedIn={setUser} />

  const account = (
    <section className="card account">
      <div>
        <div className="row-item">{user.name ?? user.email}</div>
        <div className="muted small">{user.email}</div>
      </div>
      <button className="btn small" onClick={() => auth.signOut().then(() => setUser(null))}>
        Sign out
      </button>
    </section>
  )

  return (
    <DataProvider backend={backend}>
      <Shell account={account} demo={auth.kind === 'demo'} />
      {reconnect && <Reconnect auth={auth} user={user} onSignOut={() => auth.signOut().then(() => setUser(null))} />}
    </DataProvider>
  )
}

function Shell({ account, demo }: { account: React.ReactNode; demo: boolean }) {
  const route = useRoute()
  useEffect(() => listenForShares(), []) // files shared to FinMerge open Upload and upload
  const cards = useLoad((b) => b.listCards())
  const open = cards.data?.length ?? 0

  // Upload's progress shows on its tab, wherever you are.
  const [busy] = useStored('upload.busy', false)
  const [progress] = useStored<UploadProgress | undefined>('upload.progress', undefined)

  // Each hub reopens on the sub-tab you used last (e.g. Accounts → Year).
  const hub = HUB_OF[route.name]
  const [lastAccounts, setLastAccounts] = useStored<Route>('nav.accounts', { name: 'month' })
  const [lastSheets, setLastSheets] = useStored<Route>('nav.sheets', { name: 'investments' })
  useEffect(() => {
    if (hub === 'accounts') setLastAccounts(route)
    if (hub === 'sheets') setLastSheets(route)
  }, [hub, route, setLastAccounts, setLastSheets])

  // The rule of 5: five destinations at the bottom, the action (Upload) in the middle.
  const tabs: Tab[] = [
    { key: 'home', route: { name: 'home' }, label: 'Home', icon: '⌂' },
    { key: 'accounts', route: lastAccounts, label: 'Accounts', icon: '▦' },
    { key: 'upload', route: { name: 'upload' }, label: busy && progress ? `${Math.round(progress.fraction * 100)}%` : 'Upload', icon: '⇪', primary: true, working: busy },
    { key: 'cards', route: { name: 'cards' }, label: 'To Update', icon: '✎', badge: open },
    { key: 'sheets', route: lastSheets, label: 'Sheets', icon: '▤' },
  ]
  const subs = hub === 'accounts' || hub === 'sheets' ? SUBS[hub] : null

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <img src="./icon.svg" alt="" width={28} height={28} />
          FinMerge
        </div>
        {/* Wide screens have room: every place is in view, sub-pages under their hub. */}
        <nav className="side-nav" aria-label="Main">
          {tabs.map((t) => (
            <div key={t.key} className="side-group">
              <NavLink tab={t} on={hub === t.key && !(t.key in SUBS)} />
              {t.key in SUBS &&
                SUBS[t.key as keyof typeof SUBS].map((s) => (
                  <a key={s.label} href={href(s.route)} className={route.name === s.route.name ? 'nav sub on' : 'nav sub'}
                    aria-current={route.name === s.route.name ? 'page' : undefined}>
                    <span className="nav-label">{s.label}</span>
                  </a>
                ))}
            </div>
          ))}
          <a href={href({ name: 'settings' })} className={route.name === 'settings' ? 'nav on push-down' : 'nav push-down'}>
            <span className="nav-icon" aria-hidden>⚙</span>
            <span className="nav-label">Settings</span>
          </a>
        </nav>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="topbar-row">
            <h1>{TITLES[route.name]}</h1>
            {demo && <span className="pill warn">Demo data</span>}
            {/* Settings is rarely needed: one tap away up here, not a bottom tab. */}
            <a className={route.name === 'settings' ? 'icon-btn settings-link on' : 'icon-btn settings-link'} href={href({ name: 'settings' })} aria-label="Settings">
              ⚙
            </a>
          </div>
          {subs && (
            <nav className="subtabs" aria-label={hub === 'accounts' ? 'Accounts' : 'Sheets'}>
              {subs.map((s) => (
                <a key={s.label} href={href(s.route)} className={route.name === s.route.name ? 'subtab on' : 'subtab'}
                  aria-current={route.name === s.route.name ? 'page' : undefined}>
                  {s.label}
                </a>
              ))}
            </nav>
          )}
        </header>
        <div className={route.name === 'month' ? 'content wide' : 'content'}>
          {route.name === 'home' && <Home />}
          {route.name === 'upload' && <Upload />}
          {route.name === 'cards' && <Cards />}
          {route.name === 'month' && <Month year={route.year} month={route.month} />}
          {route.name === 'year' && <Year year={route.year} />}
          {route.name === 'trips' && <Trips trip={route.trip} />}
          {route.name === 'investments' && <Sheets sheet={route.sheet} section="investments" />}
          {route.name === 'sheets' && <Sheets sheet={route.sheet} />}
          {route.name === 'settings' && <Settings tab={route.tab} account={account} />}
        </div>
      </main>
      <nav className="bottom-nav" aria-label="Main">
        {tabs.map((t) => (
          <NavLink key={t.key} tab={t} on={hub === t.key} />
        ))}
      </nav>
    </div>
  )
}

type Hub = 'home' | 'accounts' | 'upload' | 'cards' | 'sheets'
interface Tab {
  key: Hub
  route: Route
  label: string
  icon: string
  badge?: number
  primary?: boolean
  working?: boolean
}

/** Which bottom tab a page belongs to (Settings: none, it's in the header). */
const HUB_OF: Record<Route['name'], Hub | null> = {
  home: 'home', month: 'accounts', year: 'accounts', trips: 'accounts', upload: 'upload', cards: 'cards',
  investments: 'sheets', sheets: 'sheets', settings: null,
}

/** The pages inside a hub, as tabs across its top: all visible, nothing behind "More". */
const SUBS: Record<'accounts' | 'sheets', { route: Route; label: string }[]> = {
  accounts: [
    { route: { name: 'month' }, label: 'Month' },
    { route: { name: 'year' }, label: 'Year' },
    { route: { name: 'trips' }, label: 'Trips' },
  ],
  sheets: [
    { route: { name: 'investments' }, label: 'Investments' },
    { route: { name: 'sheets' }, label: 'Other sheets' },
  ],
}

function NavLink({ tab, on }: { tab: Tab; on: boolean }) {
  const cls = ['nav', on && 'on', tab.primary && 'primary', tab.working && 'working'].filter(Boolean).join(' ')
  return (
    <a href={href(tab.route)} className={cls} aria-current={on ? 'page' : undefined}>
      <span className="nav-icon" aria-hidden>
        {tab.icon}
      </span>
      <span className="nav-label">{tab.label}</span>
      {!!tab.badge && <span className="badge">{tab.badge > 99 ? '99+' : tab.badge}</span>}
    </a>
  )
}

function SignIn({ auth, onSignedIn }: { auth: Auth; onSignedIn(u: User): void }) {
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)
  return (
    <div className="signin">
      <div className="card signin-card">
        <img src="./icon.svg" alt="" width={56} height={56} />
        <h1>FinMerge</h1>
        <p className="muted">
          Your bank and e-wallet statements, compiled into your monthly accounts in Google Sheets. Everything runs on
          this device and goes only to your own Drive.
        </p>
        <button
          className="btn google"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            setError(undefined)
            try {
              onSignedIn(await auth.signIn())
            } catch (e) {
              setError(errorText(e))
            } finally {
              setBusy(false)
            }
          }}
        >
          <GoogleG />
          {busy ? 'Signing in…' : 'Sign in with Google'}
        </button>
        {auth.kind === 'demo' && <p className="muted small">Demo mode: no Google account is used, the data is made up.</p>}
        {error && <p className="error-text">{error}</p>}
      </div>
    </div>
  )
}

/** Google needs a click to hand out a new token (page reopened, or the hour ran out). */
function Reconnect({ auth, user, onSignOut }: { auth: Auth; user: User; onSignOut(): void }) {
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)
  return (
    <div className="sheet-backdrop">
      <div className="sheet" role="dialog" aria-modal="true" aria-label="Continue with Google">
        <div className="stack">
          <h2>Continue with Google</h2>
          <p className="muted">
            For your security, Google access lasts about an hour. Continue as <strong>{user.email}</strong> to keep
            going.
          </p>
          {error && <p className="error-text">{error}</p>}
          <div className="btn-row end">
            <button className="btn ghost" onClick={onSignOut} disabled={busy}>
              Sign out
            </button>
            <button
              className="btn google"
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                setError(undefined)
                try {
                  await auth.reconnect?.()
                } catch (e) {
                  setError(errorText(e))
                } finally {
                  setBusy(false)
                }
              }}
            >
              <GoogleG />
              {busy ? 'Connecting…' : 'Continue'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.6 2.4 30.2 0 24 0 14.6 0 6.6 5.4 2.7 13.3l7.8 6C12.4 13.6 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.6 5.9c4.4-4.1 7-10.1 7-17.6z" />
      <path fill="#FBBC05" d="M10.5 28.7c-.5-1.4-.8-3-.8-4.7s.3-3.2.8-4.7l-7.8-6C1 16.6 0 20.2 0 24s1 7.4 2.7 10.7l7.8-6z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2.1 1.4-4.9 2.3-8.3 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.8 6C6.6 42.6 14.6 48 24 48z" />
    </svg>
  )
}
