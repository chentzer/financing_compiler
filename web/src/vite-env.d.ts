/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" (default) or "real". */
  readonly VITE_BACKEND?: string
  /** OAuth Web client ID for Google Identity Services. */
  readonly VITE_GOOGLE_CLIENT_ID?: string
  readonly VITE_ALLOWED_EMAILS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
