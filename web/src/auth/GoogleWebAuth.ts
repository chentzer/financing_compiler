import { ALLOWED_EMAILS, GOOGLE_SCOPES, NotAllowedError, type Auth, type User } from './Auth'

// Minimal typings for the parts of Google Identity Services we use.
interface TokenResponse {
  access_token: string
  expires_in: number
  error?: string
  error_description?: string
}
interface TokenClient {
  requestAccessToken(overrides?: { prompt?: string; login_hint?: string }): void
}
declare global {
  interface Window {
    google?: {
      accounts: {
        oauth2: {
          initTokenClient(config: {
            client_id: string
            scope: string
            callback: (r: TokenResponse) => void
            error_callback?: (e: { type: string; message?: string }) => void
          }): TokenClient
          revoke(token: string, done?: () => void): void
        }
      }
    }
  }
}

const GIS_SRC = 'https://accounts.google.com/gsi/client'
const USER_KEY = 'fincomp.user'
// The access token (about an hour) survives closing the page, so reopening doesn't ask again.
const TOKEN_KEY = 'fincomp.token'

function loadGis(): Promise<void> {
  if (window.google?.accounts) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = GIS_SRC
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('Could not load Google sign-in.'))
    document.head.appendChild(s)
  })
}

// Renew on your next tap once less than this is left.
const RENEW_BEFORE_MS = 15 * 60_000

/**
 * Web sign-in with the Google Identity Services token client. Google gives
 * a browser-only app an access token for an hour and no refresh token, and
 * asking for a new one opens a popup (closing by itself when you already
 * agreed) that browsers only allow straight after a tap. So the app stays
 * signed in by renewing on your taps: in the last 15 minutes of the hour,
 * the next tap anywhere quietly gets a new token. Only after more than an
 * hour away does a call have to wait for "Continue". The Android app renews
 * without any of this (NativeAuth).
 */
export class GoogleWebAuth implements Auth {
  readonly kind = 'google-web' as const
  private client?: TokenClient
  private token?: { value: string; expires: number }
  private user: User | null
  private pending?: { resolve: (t: TokenResponse) => void; reject: (e: Error) => void }
  /** Calls waiting for a token until the user clicks Continue. */
  private waiting?: { promise: Promise<string>; resolve: (t: string) => void }
  private listeners = new Set<(needed: boolean) => void>()

  private clientId: string

  constructor(clientId: string) {
    this.clientId = clientId
    try {
      this.user = JSON.parse(localStorage.getItem(USER_KEY) ?? 'null')
      const t = JSON.parse(localStorage.getItem(TOKEN_KEY) ?? 'null')
      if (this.user && t?.value && t.expires > Date.now() + 60_000) this.token = t
    } catch {
      this.user = null
    }
    if (this.user) loadGis().catch(() => undefined) // ready before the first tap
    document.addEventListener('click', () => this.renewOnTap(), true)
  }

  /** A tap is the one moment a popup is allowed: renew the token while it's nearly used up. */
  private renewOnTap(): void {
    if (!this.user || this.pending || this.waiting) return // "Continue" handles a token already gone
    if (this.token && this.token.expires > Date.now() + RENEW_BEFORE_MS) return
    this.request('').catch(() => undefined) // closed or blocked: try again on a later tap
  }

  currentUser(): User | null {
    return this.user
  }

  async signIn(): Promise<User> {
    const t = await this.request('consent')
    const user = await this.fetchUser(t.access_token)
    if (ALLOWED_EMAILS.length && !ALLOWED_EMAILS.includes(user.email.toLowerCase())) {
      window.google?.accounts.oauth2.revoke(t.access_token)
      this.token = undefined
      throw new NotAllowedError(user.email)
    }
    this.user = user
    this.release()
    try {
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    } catch {
      /* storage blocked: stay signed in for this visit only */
    }
    return user
  }

  async signOut(): Promise<void> {
    if (this.token) window.google?.accounts.oauth2.revoke(this.token.value)
    this.token = undefined
    this.user = null
    try {
      localStorage.removeItem(USER_KEY)
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* ignore */
    }
  }

  async getAccessToken(): Promise<string> {
    if (this.token && this.token.expires > Date.now() + 60_000) return this.token.value
    if (!this.waiting) {
      let resolve!: (t: string) => void
      const promise = new Promise<string>((r) => (resolve = r))
      this.waiting = { promise, resolve }
      this.listeners.forEach((l) => l(true))
    }
    return this.waiting.promise
  }

  onReconnectNeeded(listener: (needed: boolean) => void): () => void {
    this.listeners.add(listener)
    if (this.waiting) listener(true)
    return () => this.listeners.delete(listener)
  }

  /** From a click: get a fresh token (no consent screen again) and let waiting calls go on. */
  async reconnect(): Promise<void> {
    const t = await this.request('')
    this.release()
    // Pick up your name if you first signed in before the app asked for it.
    if (this.user && !this.user.name) {
      try {
        this.user = { ...this.user, ...(await this.fetchUser(t.access_token)) }
        localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      } catch {
        /* keep the email-only profile */
      }
    }
  }

  private release(): void {
    const w = this.waiting
    if (!w || !this.token) return
    this.waiting = undefined
    w.resolve(this.token.value)
    this.listeners.forEach((l) => l(false))
  }

  private async request(prompt: string): Promise<TokenResponse> {
    await loadGis()
    if (!this.client) {
      this.client = window.google!.accounts.oauth2.initTokenClient({
        client_id: this.clientId,
        scope: GOOGLE_SCOPES.join(' '),
        callback: (r) => {
          const p = this.pending
          this.pending = undefined
          if (r.error) p?.reject(new Error(r.error_description || r.error))
          else {
            this.token = { value: r.access_token, expires: Date.now() + r.expires_in * 1000 }
            try {
              localStorage.setItem(TOKEN_KEY, JSON.stringify(this.token))
            } catch {
              /* storage blocked: the token lasts this visit only */
            }
            p?.resolve(r)
          }
        },
        error_callback: (e) => {
          const p = this.pending
          this.pending = undefined
          p?.reject(new Error(e.message || `Sign-in ${e.type.replace(/_/g, ' ')}.`))
        },
      })
    }
    // A newer popup replaces one that was closed without an answer.
    if (this.pending) this.pending.reject(new Error('Sign-in was started again.'))
    return new Promise((resolve, reject) => {
      this.pending = { resolve, reject }
      this.client!.requestAccessToken({ prompt, login_hint: this.user?.email })
    })
  }

  private async fetchUser(token: string): Promise<User> {
    const r = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!r.ok) throw new Error('Could not read your Google profile.')
    const j = await r.json()
    return { email: j.email, name: j.name, picture: j.picture }
  }
}
