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

/**
 * Web sign-in with the Google Identity Services token client. The token
 * lives only in memory (about an hour); when it runs out the next call
 * asks Google again, which is silent if the user already consented.
 */
export class GoogleWebAuth implements Auth {
  readonly kind = 'google-web' as const
  private client?: TokenClient
  private token?: { value: string; expires: number }
  private user: User | null
  private pending?: { resolve: (t: TokenResponse) => void; reject: (e: Error) => void }

  private clientId: string

  constructor(clientId: string) {
    this.clientId = clientId
    try {
      this.user = JSON.parse(localStorage.getItem(USER_KEY) ?? 'null')
    } catch {
      this.user = null
    }
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
    } catch {
      /* ignore */
    }
  }

  async getAccessToken(): Promise<string> {
    if (this.token && this.token.expires > Date.now() + 60_000) return this.token.value
    const t = await this.request('')
    return t.access_token
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
