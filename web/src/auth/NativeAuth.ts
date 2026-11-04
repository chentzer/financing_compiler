import { registerPlugin } from '@capacitor/core'
import { SocialLogin } from '@capgo/capacitor-social-login'
import { ALLOWED_EMAILS, GOOGLE_SCOPES, NotAllowedError, type Auth, type User } from './Auth'
import { getQuietRenew } from './renew'

const USER_KEY = 'fincomp.user'
// The access token (an hour) is kept on this phone, so reopening the app doesn't ask again.
const TOKEN_KEY = 'fincomp.token'
// Google access tokens last an hour; ask again a little before.
const TOKEN_LIFE_MS = 55 * 60_000

/** A token for the saved account with no screen at all (android/.../QuietTokenPlugin.java). */
const QuietToken = registerPlugin<{
  get(o: { email: string; scopes: string[]; refused?: string }): Promise<{ token: string }>
}>('QuietToken')

/**
 * Google sign-in for the Android app. Google blocks its web sign-in inside
 * app WebViews, so this uses Android's own account picker through
 * @capgo/capacitor-social-login. It needs, in the same Google Cloud project
 * as the website:
 * - an Android OAuth client for package com.chentzer.fincomp with the
 *   SHA-1 of the key that signs the APK, and
 * - the Web client ID (VITE_GOOGLE_CLIENT_ID), passed here as webClientId,
 *   so the access token carries GOOGLE_SCOPES.
 * The scopes need MainActivity to hand results back to the plugin (see
 * android/app/src/main/java/.../MainActivity.java).
 */
export class NativeAuth implements Auth {
  readonly kind = 'google-native' as const
  private ready?: Promise<void>
  private token?: { value: string; expires: number }
  private user: User | null
  private webClientId: string
  /** Quiet renewal off: calls waiting for "Continue" (as on the web). */
  private waiting?: { promise: Promise<string>; resolve: (t: string) => void }
  private listeners = new Set<(needed: boolean) => void>()
  /** The token Google refused: Android has it cached, so it's cleared before asking for a new one. */
  private refused?: string
  /** The sign-in in progress: every call waiting for a token shares it (one account chooser, not one per call). */
  private inFlight?: Promise<User>

  constructor(webClientId: string) {
    this.webClientId = webClientId
    try {
      this.user = JSON.parse(localStorage.getItem(USER_KEY) ?? 'null')
      const t = JSON.parse(localStorage.getItem(TOKEN_KEY) ?? 'null')
      if (this.user && t?.value && t.expires > Date.now() + 60_000) this.token = t
    } catch {
      this.user = null
    }
  }

  currentUser(): User | null {
    return this.user
  }

  async signIn(): Promise<User> {
    const user = await this.login(true)
    if (ALLOWED_EMAILS.length && !ALLOWED_EMAILS.includes(user.email.toLowerCase())) {
      await this.signOut()
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
    this.token = undefined
    this.user = null
    try {
      localStorage.removeItem(USER_KEY)
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* ignore */
    }
    try {
      await this.init()
      await SocialLogin.logout({ provider: 'google' })
    } catch {
      /* already signed out */
    }
  }

  async getAccessToken(): Promise<string> {
    if (this.token && this.token.expires > Date.now() + 60_000) return this.token.value
    // The first token after opening the app is fetched quietly either way;
    // with quiet renewal off, each one after that waits for "Continue".
    if (this.token && !getQuietRenew()) {
      if (!this.waiting) {
        let resolve!: (t: string) => void
        const promise = new Promise<string>((r) => (resolve = r))
        this.waiting = { promise, resolve }
        this.listeners.forEach((l) => l(true))
      }
      return this.waiting.promise
    }
    await this.login() // no picker when this account already allowed these scopes
    return this.token!.value
  }

  invalidate(): void {
    this.refused = this.token?.value ?? this.refused
    this.token = undefined
    try {
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* ignore */
    }
  }

  onReconnectNeeded(listener: (needed: boolean) => void): () => void {
    this.listeners.add(listener)
    if (this.waiting) listener(true)
    return () => this.listeners.delete(listener)
  }

  async reconnect(): Promise<void> {
    await this.login()
    const w = this.waiting
    this.waiting = undefined
    w?.resolve(this.token!.value)
    this.listeners.forEach((l) => l(false))
  }

  private keepToken(value: string): void {
    this.token = { value, expires: Date.now() + TOKEN_LIFE_MS }
    try {
      localStorage.setItem(TOKEN_KEY, JSON.stringify(this.token))
    } catch {
      /* storage blocked: a new one is fetched next time the app opens */
    }
  }

  private init(): Promise<void> {
    this.ready ??= SocialLogin.initialize({ google: { webClientId: this.webClientId, mode: 'online' } })
    return this.ready
  }

  /** One sign-in at a time; `choose` shows the account chooser (first sign-in only). */
  private login(choose = false): Promise<User> {
    this.inFlight ??= this.loginOnce(choose).finally(() => {
      this.inFlight = undefined
    })
    return this.inFlight
  }

  private async loginOnce(choose: boolean): Promise<User> {
    // Already signed in: a new token for that account, with no screen.
    if (!choose && this.user) {
      try {
        const { token } = await QuietToken.get({ email: this.user.email, scopes: GOOGLE_SCOPES, refused: this.refused })
        this.refused = undefined
        this.keepToken(token)
        return this.user
      } catch {
        /* needs a screen (e.g. access was removed): the sign-in below */
      }
    }
    await this.init()
    const quiet = !choose && !!this.user
    const ask = (q: boolean) => SocialLogin.login({
      provider: 'google',
      // These two only work with style "bottom"; the default style always shows the chooser.
      options: { scopes: GOOGLE_SCOPES, ...(q ? { style: 'bottom' as const, filterByAuthorizedAccounts: true, autoSelectEnabled: true } : {}) },
    })
    let res: Awaited<ReturnType<typeof ask>>
    try {
      res = await ask(quiet)
    } catch (e) {
      if (!quiet) throw e
      res = await ask(false) // no account remembered on this phone: show the chooser once
    }
    const r = res.result as {
      accessToken?: { token: string } | null
      profile?: { email?: string | null; name?: string | null; imageUrl?: string | null }
    }
    const token = r.accessToken?.token
    if (!token) throw new Error('Google sign-in did not return access to Sheets and Drive. Try again.')
    this.refused = undefined
    this.keepToken(token)
    const email = r.profile?.email ?? this.user?.email
    if (!email) throw new Error('Google sign-in did not say which account was used.')
    return { email, name: r.profile?.name ?? undefined, picture: r.profile?.imageUrl ?? undefined }
  }
}
