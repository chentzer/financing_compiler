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

/** Where each page was scrolled to, so coming back to it lands in the same place. */
const scrolled = new Map<string, number>()

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash))
  useEffect(() => {
    let page = window.location.hash
    const onScroll = () => {
      // Mid-switch the address already says the next page while this one is reset to the top: skip that.
      if (window.location.hash === page) scrolled.set(page, window.scrollY)
    }
    const on = () => {
      page = window.location.hash
      setRoute(parseRoute(page))
      // The page may still be drawing: keep trying until it is tall enough (up to a second).
      const want = scrolled.get(page) ?? 0
      const until = Date.now() + 1000
      const tryScroll = () => {
        window.scrollTo(0, want)
        if (Math.abs(window.scrollY - want) > 2 && Date.now() < until) setTimeout(tryScroll, 30)
      }
      window.scrollTo(0, want)
      setTimeout(tryScroll, 0)
    }
    window.addEventListener('hashchange', on)
    window.addEventListener('scroll', onScroll, { passive: true })
    // Also on every tap, before a link can change the page (scroll events can lag behind).
    window.addEventListener('click', onScroll, true)
    return () => {
      window.removeEventListener('hashchange', on)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('click', onScroll, true)
    }
  }, [])
  return route
}
