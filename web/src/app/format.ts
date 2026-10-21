const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export function rm(n: number): string {
  return `RM ${n.toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** "+RM 12.00" / "-RM 12.00" for a row of the given kind. */
export function signedRm(amount: number, kind: 'spend' | 'earn'): string {
  return `${kind === 'earn' ? '+' : '-'}${rm(amount)}`
}

export function monthName(year: number, month: number): string {
  return `${MONTHS[month - 1]} ${year}`
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
