import type { Auth, User } from './Auth'

/**
 * Real mode, but the build has no Google OAuth client ID yet
 * (GOOGLE_CLIENT_ID repo variable). Signing in explains what's missing
 * instead of the app failing to start.
 */
export class NotConfiguredAuth implements Auth {
  readonly kind = 'google-web' as const

  currentUser(): User | null {
    return null
  }

  async signIn(): Promise<User> {
    throw new Error(
      "Google sign-in isn't set up for this site yet: it needs a Google OAuth client ID " +
        '(GOOGLE_CLIENT_ID in the repo’s Actions variables). See "One-time Google setup" in the README.',
    )
  }

  async signOut(): Promise<void> {}

  async getAccessToken(): Promise<string> {
    throw new Error("Google sign-in isn't set up for this site yet.")
  }
}
