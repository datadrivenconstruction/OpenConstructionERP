/**
 * Field PWA service worker (offline slice, TOP-30 #14).
 *
 * This is a small, dependency-free service worker dedicated to the field shell.
 * It is registered with `scope: '/field'` by `registerFieldServiceWorker()` so
 * it does NOT collide with:
 *   - the workbox SW that `vite-plugin-pwa` emits at `/sw.js` (app-wide), and
 *   - the deliberate self-destruct stub checked in at `public/sw.js`
 *     (which clears caches + unregisters the old root SW; see its header).
 *
 * Correctness of field data never depends on this worker: the IndexedDB
 * mutation queue (`shared/lib/offline/mutationQueue.ts`) is the source of truth
 * for unsynced writes. This worker is purely an accelerator so the field shell
 * and the last-viewed read data paint instantly and load when fully offline.
 *
 * Two cache lanes:
 *   - oe-field-shell    precache of the app shell entry, served as the offline
 *                       navigation fallback so a cold `/field` open works.
 *   - oe-field-data     runtime NetworkFirst for `/api/v1/field-diary/*` GETs
 *                       (e.g. the Today screen) so the last-viewed data is
 *                       available offline. Mutations bypass the SW entirely.
 */

/* eslint-disable no-restricted-globals */

const SHELL_CACHE = 'oe-field-shell-v1';
const DATA_CACHE = 'oe-field-data-v1';

// The SPA entry. Caching index.html lets a cold offline open of /field paint
// the shell, which then mounts the field routes from the bundled JS (already
// served via the browser HTTP cache / workbox precache when present).
const SHELL_URLS = ['/', '/index.html'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // addAll is all-or-nothing; tolerate a missing entry so install never
      // wedges on a dev server that does not serve one of the URLs.
      await Promise.all(
        SHELL_URLS.map((url) =>
          cache.add(url).catch(() => {
            /* tolerate */
          }),
        ),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((k) => k.startsWith('oe-field-') && k !== SHELL_CACHE && k !== DATA_CACHE)
          .map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

function isFieldDataRequest(url) {
  // Read-cache for the offline field flows: today's diary and its recent days, time, checklist templates.
  return (
    url.pathname.startsWith('/api/v1/field-diary/') ||
    url.pathname.startsWith('/api/v1/field/') ||
    url.pathname.startsWith('/api/v1/field-time/') ||
    url.pathname.startsWith('/api/v1/daily-diary/') ||
    url.pathname.startsWith('/api/v1/inspections/')
  );
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') {
    // Never intercept writes: the mutation queue owns those.
    return;
  }
  const url = new URL(req.url);

  // Field read data: NetworkFirst with a cache fallback so the last-viewed
  // Today screen survives going offline.
  if (isFieldDataRequest(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(DATA_CACHE);
        try {
          const fresh = await fetch(req);
          if (fresh && fresh.status === 200) {
            cache.put(req, fresh.clone());
          }
          return fresh;
        } catch {
          const cached = await cache.match(req);
          if (cached) return cached;
          throw new Error('offline and no cached field data');
        }
      })(),
    );
    return;
  }

  // SPA navigation requests: serve the cached shell when offline so a refresh
  // on /field deep-links does not break.
  if (req.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          return await fetch(req);
        } catch {
          const cache = await caches.open(SHELL_CACHE);
          const cached = (await cache.match('/index.html')) || (await cache.match('/'));
          if (cached) return cached;
          throw new Error('offline and no cached shell');
        }
      })(),
    );
  }
});
