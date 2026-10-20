/**
 * Statement passwords, encrypted with the user's PIN.
 *
 * - Key: PBKDF2-SHA256 over the PIN with a random 16-byte salt and 600,000
 *   iterations (OWASP 2023), giving an AES-256-GCM key. A new salt is made
 *   whenever the PIN is set or changed.
 * - Every save encrypts with a fresh random 12-byte IV.
 * - Only this blob ever leaves the device (Drive App Data folder). The
 *   readable passwords exist only in memory while the vault is unlocked.
 * - "Remember on this device" keeps the derived key in IndexedDB as a
 *   non-extractable CryptoKey: the page can use it to decrypt, but can't
 *   read the key out, and the PIN itself is never stored.
 *
 * Same format as fincomp/vault.py, so the CLI and the app read each other's.
 */

export const ITERATIONS = 600_000

export interface VaultBlob {
  v: 1
  kdf: 'PBKDF2-SHA256'
  iterations: number
  salt: string // base64
  iv: string // base64
  data: string // base64 AES-GCM ciphertext + tag of the passwords JSON
}

export class WrongPinError extends Error {
  constructor() {
    super("That PIN didn't unlock your saved passwords.")
  }
}

const enc = new TextEncoder()
const dec = new TextDecoder()
const b64 = (b: Uint8Array) => btoa(String.fromCharCode(...b))
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0))

export function newSalt(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(16))
}

export async function deriveKey(pin: string, salt: Uint8Array, iterations = ITERATIONS): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey('raw', enc.encode(pin), 'PBKDF2', false, ['deriveKey'])
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations },
    base,
    { name: 'AES-GCM', length: 256 },
    false, // non-extractable
    ['encrypt', 'decrypt'],
  )
}

export async function seal(passwords: Record<string, string>, key: CryptoKey, salt: Uint8Array): Promise<VaultBlob> {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, enc.encode(JSON.stringify(passwords))))
  return { v: 1, kdf: 'PBKDF2-SHA256', iterations: ITERATIONS, salt: b64(salt), iv: b64(iv), data: b64(ct) }
}

export async function open(blob: VaultBlob, key: CryptoKey): Promise<Record<string, string>> {
  try {
    const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(blob.iv) }, key, unb64(blob.data))
    return JSON.parse(dec.decode(pt))
  } catch {
    throw new WrongPinError()
  }
}

export function saltOf(blob: VaultBlob): Uint8Array {
  return unb64(blob.salt)
}

// ---- this device: remembered key + a local copy of the blob -------------------------

const DB = 'fincomp-vault'
const STORE = 'keys'
const LOCAL_BLOB = 'fincomp.vault'

function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1)
    r.onupgradeneeded = () => r.result.createObjectStore(STORE)
    r.onsuccess = () => resolve(r.result)
    r.onerror = () => reject(r.error)
  })
}

async function idb<T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest): Promise<T> {
  const d = await db()
  return new Promise<T>((resolve, reject) => {
    const req = run(d.transaction(STORE, mode).objectStore(STORE))
    req.onsuccess = () => resolve(req.result as T)
    req.onerror = () => reject(req.error)
  })
}

/** The remembered key, if it belongs to this salt (the PIN wasn't changed elsewhere). */
export async function rememberedKey(salt: string): Promise<CryptoKey | null> {
  try {
    const got = await idb<{ key: CryptoKey; salt: string } | undefined>('readonly', (s) => s.get('vault'))
    return got && got.salt === salt ? got.key : null
  } catch {
    return null
  }
}

export async function remember(key: CryptoKey, salt: string): Promise<void> {
  try {
    await idb('readwrite', (s) => s.put({ key, salt }, 'vault'))
  } catch {
    /* storage blocked: unlocked for this visit only */
  }
}

export async function forget(): Promise<void> {
  try {
    await idb('readwrite', (s) => s.delete('vault'))
  } catch {
    /* nothing remembered */
  }
}

export function localBlob(): VaultBlob | null {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_BLOB) ?? 'null')
  } catch {
    return null
  }
}

export function keepLocal(blob: VaultBlob): void {
  try {
    localStorage.setItem(LOCAL_BLOB, JSON.stringify(blob))
  } catch {
    /* storage blocked */
  }
}
