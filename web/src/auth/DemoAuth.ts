import type { Auth, User } from './Auth'

/** Used with MockBackend: "signs in" a made-up user without Google. */
export class DemoAuth implements Auth {
  readonly kind = 'demo' as const
  private user: User | null = null

  currentUser(): User | null {
    return this.user
  }

  async signIn(): Promise<User> {
    this.user = { email: 'demo@example.com', name: 'Demo user' }
    return this.user
  }

  async signOut(): Promise<void> {
    this.user = null
  }

  async getAccessToken(): Promise<string> {
    return 'demo-token'
  }
}
