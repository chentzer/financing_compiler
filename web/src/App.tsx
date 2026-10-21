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
  const cards = useLoad((b) => b.listCards())
  const open = cards.data?.length ?? 0

  const nav: { route: Route; label: string; icon: string; badge?: number }[] = [
    { route: { name: 'home' }, label: 'Home', icon: '⌂' },
    { route: { name: 'cards' }, label: 'To Update', icon: '✎', badge: open },
    { route: { name: 'upload' }, label: 'Upload', icon: '⇪' },
    { route: { name: 'month' }, label: 'Month', icon: '▦' },
    { route: { name: 'year' }, label: 'Year', icon: '▥' },
    { route: { name: 'trips' }, label: 'Trips', icon: '✈' },
    { route: { name: 'investments' }, label: 'Invest', icon: '↗' },
    { route: { name: 'sheets' }, label: 'Sheets', icon: '▤' },
    { route: { name: 'settings' }, label: 'Settings', icon: '⚙' },
  ]

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <img src="./icon.svg" alt="" width={28} height={28} />
          FinMerge
        </div>
        <NavLinks items={nav} current={route.name} />
      </aside>
      <main className="main">
        <header className="topbar">
          <h1>{TITLES[route.name]}</h1>
          {demo && <span className="pill warn">Demo data</span>}
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
        <NavLinks items={nav} current={route.name} />
      </nav>
    </div>
  )
}

function NavLinks({
  items,
  current,
}: {
  items: { route: Route; label: string; icon: string; badge?: number }[]
  current: Route['name']
}) {
  return (
    <>
      {items.map((n) => (
        <a
          key={n.route.name}
          href={href(n.route)}
          className={n.route.name === current ? 'nav on' : 'nav'}
          aria-current={n.route.name === current ? 'page' : undefined}
        >
          <span className="nav-icon" aria-hidden>
            {n.icon}
          </span>
          <span className="nav-label">{n.label}</span>
          {!!n.badge && <span className="badge">{n.badge}</span>}
        </a>
      ))}
    </>
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
