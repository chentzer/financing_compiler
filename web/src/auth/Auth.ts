/**
 * Google sign-in, behind one interface so the web build (Google Identity
 * Services) and the Android app (native sign-in via a Capacitor plugin)
 * can swap implementations. The real Backend asks `getAccessToken()` for
 * every Sheets / Drive call.
 */

export const GOOGLE_SCOPES = [
  'openid',
  'email',
  'https://www.googleapis.com/auth/spreadsheets',
  'https://www.googleapis.com/auth/drive.file',
  'https://www.googleapis.com/auth/drive.appdata',
]

/**
 * Optional extra lock: comma-separated emails in VITE_ALLOWED_EMAILS at build
 * time. Empty = anyone may sign in, which is safe: the app only ever opens
 * the signed-in person's own Drive, and while the Google sign-in is in
 * "Testing" mode only listed test users can sign in at all. Kept out of
 * the code because the repo is public.
 */
export const ALLOWED_EMAILS: string[] = (import.meta.env.VITE_ALLOWED_EMAILS ?? '')
  .split(',')
  .map((e: string) => e.trim().toLowerCase())
  .filter(Boolean)

export interface User {
  email: string
  name?: string
  picture?: string
}

export interface Auth {
  /** Short label shown on the sign-in screen. */
  readonly kind: 'google-web' | 'google-native' | 'demo'
  currentUser(): User | null
  signIn(): Promise<User>
  signOut(): Promise<void>
  /** A valid OAuth access token, refreshing it if needed. */
  getAccessToken(): Promise<string>
  /**
   * Web only: browsers block Google's popup unless it comes from a click.
   * When a token is needed and none is usable (page reopened, or the hour
   * ran out), calls wait and `listener(true)` fires; the app shows a
   * "Continue" button that calls reconnect(). Returns an unsubscribe.
   */
  onReconnectNeeded?(listener: (needed: boolean) => void): () => void
  reconnect?(): Promise<void>
}

export class NotAllowedError extends Error {
  constructor(email: string) {
    super(`${email} isn't allowed to use this app.`)
  }
}
