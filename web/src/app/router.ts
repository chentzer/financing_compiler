import { useEffect, useState } from 'react'

/**
 * Hash routes, so the same build works on GitHub Pages and in Capacitor
 * without server rewrites:
 *   #/  #/upload  #/cards  #/month/2026-09  #/year/2026  #/trips  #/trips/<name>  #/investments  #/sheets  #/sheets/<name>  #/settings/rules
 */
export type Route =
  | { name: 'home' }
  | { name: 'upload' }
  | { name: 'cards' }
  | { name: 'month'; year?: number; month?: number }
  | { name: 'year'; year?: number }
  | { name: 'trips'; trip?: string }
  | { name: 'investments'; sheet?: string }
  | { name: 'sheets'; sheet?: string }
  | { name: 'settings'; tab?: string }

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  switch (parts[0]) {
    case 'upload':
      return { name: 'upload' }
    case 'cards':
      return { name: 'cards' }
    case 'month': {
      const m = parts[1]?.match(/^(\d{4})-(\d{2})$/)
      return m ? { name: 'month', year: +m[1], month: +m[2] } : { name: 'month' }
    }
    case 'year':
      return /^\d{4}$/.test(parts[1] ?? '') ? { name: 'year', year: +parts[1] } : { name: 'year' }
    case 'trips':
      return { name: 'trips', trip: parts[1] ? decodeURIComponent(parts[1]) : undefined }
    case 'investments':
      return { name: 'investments', sheet: parts[1] ? decodeURIComponent(parts[1]) : undefined }
    case 'sheets':
      return { name: 'sheets', sheet: parts[1] ? decodeURIComponent(parts[1]) : undefined }
    case 'settings':
      return { name: 'settings', tab: parts[1] }
    default:
      return { name: 'home' }
  }
}

export function href(r: Route): string {
  switch (r.name) {
    case 'home':
      return '#/'
    case 'month':
      return r.year ? `#/month/${r.year}-${String(r.month).padStart(2, '0')}` : '#/month'
    case 'settings':
      return r.tab ? `#/settings/${r.tab}` : '#/settings'
    case 'year':
      return r.year ? `#/year/${r.year}` : '#/year'
    case 'trips':
      return r.trip ? `#/trips/${encodeURIComponent(r.trip)}` : '#/trips'
    case 'investments':
      return r.sheet ? `#/investments/${encodeURIComponent(r.sheet)}` : '#/investments'
    case 'sheets':
      return r.sheet ? `#/sheets/${encodeURIComponent(r.sheet)}` : '#/sheets'
    default:
      return `#/${r.name}`
  }
}

export function go(r: Route): void {
  window.location.hash = href(r)
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash))
  useEffect(() => {
    const on = () => {
      setRoute(parseRoute(window.location.hash))
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}
