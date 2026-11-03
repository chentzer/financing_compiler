import { Capacitor, registerPlugin } from '@capacitor/core'
import type { UploadProgress } from '../data/Backend'

/**
 * Android app: keep an upload running when you switch apps or the screen
 * goes off (UploadKeeperPlugin + UploadService, with a progress
 * notification). On the website these do nothing: browsers can't run a page
 * in the background.
 */
interface UploadKeeper {
  start(o: { text: string; percent?: number }): Promise<void>
  update(o: { text: string; percent: number }): Promise<void>
  stop(o: { text?: string }): Promise<void>
}

const native = Capacitor.isNativePlatform()
const keeper = native ? registerPlugin<UploadKeeper>('UploadKeeper') : null
let lastShown = { percent: -1, at: 0 }

export async function backgroundStart(text: string): Promise<void> {
  lastShown = { percent: -1, at: 0 }
  await keeper?.start({ text, percent: 0 }).catch(() => undefined)
}

/** At most a few updates a second (Android drops notification updates that come faster). */
export function backgroundProgress(p: UploadProgress): void {
  if (!keeper) return
  const percent = Math.round(p.fraction * 100)
  const now = Date.now()
  if (percent === lastShown.percent || now - lastShown.at < 700) return
  lastShown = { percent, at: now }
  void keeper.update({ text: `${percent}% · ${p.step}`, percent }).catch(() => undefined)
}

export async function backgroundStop(doneText?: string): Promise<void> {
  await keeper?.stop({ text: doneText }).catch(() => undefined)
}

export const canRunInBackground = native
