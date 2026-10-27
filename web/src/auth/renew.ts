/**
 * "Renew Google access quietly" (Settings, per device). Google hands out
 * access an hour at a time. On: the app renews it by itself before the
 * hour runs out (web: on your next tap; Android: whenever it's needed).
 * Off: it never renews by itself, so every hour it asks you to Continue.
 */
const KEY = 'fincomp.quietRenew'

export function getQuietRenew(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'off'
  } catch {
    return true
  }
}

export function setQuietRenew(on: boolean): void {
  try {
    if (on) localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, 'off')
  } catch {
    /* storage blocked: the default (on) applies */
  }
}
