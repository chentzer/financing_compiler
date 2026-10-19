import { Capacitor } from '@capacitor/core'
import type { Auth } from './auth/Auth'
import { DemoAuth } from './auth/DemoAuth'
import { GoogleWebAuth } from './auth/GoogleWebAuth'
import { NativeAuth } from './auth/NativeAuth'
import type { Backend } from './data/Backend'
import { MockBackend } from './data/MockBackend'
import { PyodideBackend } from './data/PyodideBackend'

/**
 * Picks the Auth and Backend for this build.
 *
 * - VITE_BACKEND=mock (the default for now): MockBackend + demo sign-in.
 * - VITE_BACKEND=real: PyodideBackend (fincomp in Pyodide + Google APIs);
 *   it calls auth.getAccessToken() for every Google request.
 */
export function createAuth(): Auth {
  if (import.meta.env.VITE_BACKEND !== 'real') return new DemoAuth()
  if (Capacitor.isNativePlatform()) return new NativeAuth()
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
  if (!clientId) throw new Error('VITE_GOOGLE_CLIENT_ID is not set.')
  return new GoogleWebAuth(clientId)
}

export function createBackend(auth: Auth): Backend {
  if (import.meta.env.VITE_BACKEND === 'real') return new PyodideBackend(auth)
  return new MockBackend()
}
