import { Capacitor } from '@capacitor/core'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { createAuth } from './setup'
import './styles.css'

// The installed web app: lets Android's share menu send files to FinMerge (sw.js; no caching).
if (!Capacitor.isNativePlatform() && 'serviceWorker' in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register('./sw.js').catch(() => undefined)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App auth={createAuth()} />
  </StrictMode>,
)
