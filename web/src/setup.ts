import { Capacitor } from '@capacitor/core'
import type { Auth } from './auth/Auth'
import { DemoAuth } from './auth/DemoAuth'
import { GoogleWebAuth } from './auth/GoogleWebAuth'
import { NativeAuth } from './auth/NativeAuth'
import { NotConfiguredAuth } from './auth/NotConfiguredAuth'
import type { Backend } from './data/Backend'
import { MockBackend } from './data/MockBackend'
import { PyodideBackend } from './data/PyodideBackend'

/**
 * Picks the Auth and Backend for this build.
 *
 * - VITE_BACKEND=mock (the default in development): MockBackend + demo sign-in.
 * - VITE_BACKEND=real: PyodideBackend (fincomp in Pyodide + Google APIs);
 *   it calls auth.getAccessToken() for every Google request.
 */
export function createAuth(): Auth {
  if (import.meta.env.VITE_BACKEND !== 'real') return new DemoAuth()
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
  if (!clientId) return new NotConfiguredAuth()
  // The Android app signs in natively; its token is still issued for the Web client ID.
  if (Capacitor.isNativePlatform()) return new NativeAuth(clientId)
  return new GoogleWebAuth(clientId)
}

export function createBackend(auth: Auth): Backend {
  if (import.meta.env.VITE_BACKEND === 'real') return new PyodideBackend(auth)
  return new MockBackend()
}
