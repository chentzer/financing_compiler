const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export function rm(n: number): string {
  return money(n)
}

function money(n: number, currency = 'RM'): string {
  return `${currency} ${n.toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** "+RM 12.00" / "-RM 12.00" for a row of the given kind ("-VND 80,000.00" for a row in a trip's currency). */
export function signedRm(amount: number, kind: 'spend' | 'earn', currency?: string): string {
  return `${kind === 'earn' ? '+' : '-'}${money(amount, currency)}`
}

export function monthName(year: number, month: number): string {
  return `${MONTHS[month - 1]} ${year}`
}

/** Today on this device, as YYYY-MM-DD (toISOString is UTC: yesterday before 8am in Malaysia). */
export function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${d} ${MONTHS[m - 1].slice(0, 3)} ${y}`
}

export function dayMonth(iso: string): string {
  const [, m, d] = iso.split('-').map(Number)
  return `${d} ${MONTHS[m - 1].slice(0, 3)}`
}

/** Newest first; rows without a date go last, otherwise the order is kept. */
export function newestFirst<T extends { date?: string }>(rows: T[]): T[] {
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => (b.r.date ?? '').localeCompare(a.r.date ?? '') || a.i - b.i)
    .map((x) => x.r)
}
