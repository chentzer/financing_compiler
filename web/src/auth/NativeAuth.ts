import { SocialLogin } from '@capgo/capacitor-social-login'
import { ALLOWED_EMAILS, GOOGLE_SCOPES, NotAllowedError, type Auth, type User } from './Auth'

const USER_KEY = 'fincomp.user'
// Google access tokens last an hour; ask again a little before.
const TOKEN_LIFE_MS = 55 * 60_000

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

  constructor(webClientId: string) {
    this.webClientId = webClientId
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
    const user = await this.login()
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
    await this.login() // no picker when this account already allowed these scopes
    return this.token!.value
  }

  private init(): Promise<void> {
    this.ready ??= SocialLogin.initialize({ google: { webClientId: this.webClientId, mode: 'online' } })
    return this.ready
  }

  private async login(): Promise<User> {
    await this.init()
    const res = await SocialLogin.login({ provider: 'google', options: { scopes: GOOGLE_SCOPES } })
    const r = res.result as {
      accessToken?: { token: string } | null
      profile?: { email?: string | null; name?: string | null; imageUrl?: string | null }
    }
    const token = r.accessToken?.token
    if (!token) throw new Error('Google sign-in did not return access to Sheets and Drive. Try again.')
    this.token = { value: token, expires: Date.now() + TOKEN_LIFE_MS }
    const email = r.profile?.email ?? this.user?.email
    if (!email) throw new Error('Google sign-in did not say which account was used.')
    return { email, name: r.profile?.name ?? undefined, picture: r.profile?.imageUrl ?? undefined }
  }
}
