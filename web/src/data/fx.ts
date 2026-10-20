/**
 * Today's exchange rate, RM per 1 unit of a trip's currency. Only the two
 * currency codes are sent (to a free public rates service); nothing about
 * you or your transactions.
 */

/** Common names people type for a trip's currency, to their ISO codes. */
const NAMES: Record<string, string> = {
  yen: 'JPY', won: 'KRW', baht: 'THB', dong: 'VND', rupiah: 'IDR', peso: 'PHP', yuan: 'CNY', rmb: 'CNY',
  renminbi: 'CNY', 'nt$': 'TWD', 'nt dollar': 'TWD', 'taiwan dollar': 'TWD', 'sg dollar': 'SGD', 'singapore dollar': 'SGD',
  'hk dollar': 'HKD', 'hong kong dollar': 'HKD', dollar: 'USD', 'us dollar': 'USD', euro: 'EUR', pound: 'GBP',
  'aussie dollar': 'AUD', 'australian dollar': 'AUD', rupee: 'INR', riyal: 'SAR', dirham: 'AED',
}

/** Suggestions for the Currency field. */
export const CURRENCIES = ['JPY', 'KRW', 'THB', 'SGD', 'IDR', 'VND', 'TWD', 'HKD', 'CNY', 'PHP', 'USD', 'EUR', 'GBP', 'AUD']

export function currencyCode(name: string): string | undefined {
  const n = name.trim().toLowerCase()
  if (NAMES[n]) return NAMES[n] // before the 3-letter check: "yen" is a name, not a code
  if (/^[a-z]{3}$/.test(n)) return n.toUpperCase()
  return undefined
}

export async function rateToRm(currency: string): Promise<number> {
  const code = currencyCode(currency)
  if (!code) throw new Error(`Use a 3-letter currency code (e.g. JPY) to look up "${currency}".`)
  if (code === 'MYR') return 1
  try {
    const r = await fetch(`https://api.frankfurter.dev/v1/latest?from=${code}&to=MYR`)
    if (r.ok) {
      const rate = (await r.json())?.rates?.MYR
      if (typeof rate === 'number') return rate
    }
  } catch {
    /* try the other service */
  }
  const r = await fetch(`https://open.er-api.com/v6/latest/${code}`)
  const rate = r.ok ? (await r.json())?.rates?.MYR : undefined
  if (typeof rate !== 'number') throw new Error(`Couldn't find today's rate for ${code}. Type it in instead.`)
  return rate
}
