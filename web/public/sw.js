// FinMerge service worker: only for "Share to FinMerge" from Android's share
// menu (manifest share_target). Shared files are kept in a cache for the page
// to pick up, then the page opens on Upload. Nothing else is cached or changed:
// every other request goes to the network as usual.

const SHARE_CACHE = 'finmerge-share'

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'POST' || !url.pathname.endsWith('/share-target')) return
  e.respondWith(
    (async () => {
      const form = await e.request.formData()
      const cache = await caches.open(SHARE_CACHE)
      for (const key of await cache.keys()) await cache.delete(key)
      let i = 0
      for (const file of form.getAll('files')) {
        if (!(file instanceof File)) continue
        await cache.put(new URL(`shared/${i++}`, self.registration.scope).href,
          new Response(file, { headers: { 'x-name': encodeURIComponent(file.name) } }))
      }
      return Response.redirect(new URL('./?shared=1#/upload', self.registration.scope).href, 303)
    })(),
  )
})
