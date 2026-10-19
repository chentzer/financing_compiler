import type { Auth, User } from './Auth'

/**
 * TODO(android): native Google sign-in for the Capacitor app.
 *
 * GIS's popup flow doesn't work inside the Android WebView, so the app
 * needs a native plugin, e.g. `@capgo/capacitor-social-login` or
 * `@codetrix-studio/capacitor-google-auth`, configured with:
 * - the Android OAuth client ID (package `com.chentzer.fincomp` + the
 *   signing key's SHA-1), and
 * - the Web client ID as the server client ID, so it can return an access
 *   token with GOOGLE_SCOPES.
 * Then implement signIn() / getAccessToken() with the plugin, check the
 * email against ALLOWED_EMAILS as GoogleWebAuth does, and return this class
 * from createAuth() when Capacitor.isNativePlatform().
 */
export class NativeAuth implements Auth {
  readonly kind = 'google-native' as const

  currentUser(): User | null {
    return null
  }

  async signIn(): Promise<User> {
    throw new Error('Native Google sign-in is not set up yet.')
  }

  async signOut(): Promise<void> {}

  async getAccessToken(): Promise<string> {
    throw new Error('Native Google sign-in is not set up yet.')
  }
}
