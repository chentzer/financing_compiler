import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core'
import type { UploadFile } from '../data/Backend'
import { go } from './router'
import { setStored } from './store'

/**
 * "Share to FinMerge": files shared from another app (a bank app's PDF, a
 * Splitwise CSV, an accounts workbook) open the Upload screen and upload by
 * themselves. Android app: ShareInPlugin (android/.../ShareInPlugin.java).
 * Installed web app: the share_target in manifest.webmanifest, through sw.js.
 */
interface ShareIn {
  take(): Promise<{ files: { name: string; data: string }[] }>
  addListener(event: 'shared', listener: () => void): Promise<PluginListenerHandle>
}

const SHARE_CACHE = 'finmerge-share'

function bytes(base64: string): Uint8Array {
  const bin = atob(base64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/** Put the files on Upload and start it (Upload runs it once the PIN gate is open). */
function upload(files: UploadFile[]): void {
  if (!files.length) return
  setStored('upload.picked', files)
  setStored('upload.results', [])
  setStored('upload.error', undefined)
  setStored('upload.auto', true)
  go({ name: 'upload' })
}

/** Start listening; call once after sign-in. Returns a stop function. */
export function listenForShares(): () => void {
  if (Capacitor.isNativePlatform()) {
    const plugin = registerPlugin<ShareIn>('ShareIn')
    const pull = () =>
      plugin.take().then(({ files }) => upload(files.map((f) => ({ name: f.name, data: bytes(f.data) }))), () => undefined)
    void pull() // shared while the app was closed
    const handle = plugin.addListener('shared', pull)
    return () => void handle.then((h) => h.remove())
  }
  if (new URLSearchParams(location.search).has('shared') && 'caches' in window) {
    // Drop ?shared=1 so a reload doesn't upload again.
    history.replaceState(null, '', location.pathname + location.hash)
    void (async () => {
      const cache = await caches.open(SHARE_CACHE)
      const files: UploadFile[] = []
      for (const req of await cache.keys()) {
        const res = await cache.match(req)
        if (!res) continue
        files.push({ name: decodeURIComponent(res.headers.get('x-name') ?? 'shared.pdf'), data: new Uint8Array(await res.arrayBuffer()) })
        await cache.delete(req)
      }
      upload(files)
    })()
  }
  return () => undefined
}
