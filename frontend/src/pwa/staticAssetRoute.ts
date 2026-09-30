// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Which requests the service worker may answer from its long-lived
 * CacheFirst lane, and under which cache name.
 *
 * WHY THIS IS NARROW. The lane used to take every image request, cross-origin
 * included, and to cache status 0 as well as 200. A cross-origin ``<img>`` is
 * a no-cors request, so what comes back is an OPAQUE response: status 0, no
 * headers, no way to tell a picture from a 404. Caching status 0 therefore
 * cached failures too, and CacheFirst then served them for the full 30 days
 * without asking the network again. The video covers are the case that
 * showed it: YouTube answers a thumbnail that does not exist yet with a 404
 * grey placeholder, the first visit stored that as a success, and every later
 * visit got the placeholder back from the cache while the real thumbnail was
 * live. Only a hard reload, which bypasses the service worker, showed the
 * cover. Chrome also counts each opaque entry at a padded size of several
 * megabytes against the origin quota, so a few hundred of them can exhaust
 * it and make every other cache write fail.
 *
 * So: same origin only, status 200 only. Cross-origin images go to the
 * browser's own HTTP cache, which honours the host's cache headers and heals
 * by itself.
 *
 * The function is serialised into the generated ``sw.js`` by workbox (it is
 * copied as source text), so it must stay self-contained: no imports, no
 * references to anything outside its own parameters.
 */

/** Current name of the CacheFirst lane. Renamed so poisoned entries are left behind. */
export const STATIC_ASSETS_CACHE = 'oce-static-assets-v2';

/**
 * Earlier names of the lane. Their entries may hold cached failures, so the
 * app deletes them on start (see ``retireStaleCaches``).
 */
export const RETIRED_STATIC_ASSETS_CACHES: readonly string[] = ['oce-static-assets'];

/** What workbox hands a route's match callback, reduced to what this one reads. */
export interface StaticAssetMatch {
  url: URL;
  request: { destination: string };
  sameOrigin: boolean;
}

/**
 * True for a same-origin font, image or ``/assets/`` file. Never for another
 * origin, never for ``/api/``, never for a worker script (workers need the
 * browser's own fetch with the exact MIME type the server sent).
 */
export const isStaticAssetRequest = ({ url, request, sameOrigin }: StaticAssetMatch): boolean => {
  if (!sameOrigin) return false;
  if (url.pathname.startsWith('/api/')) return false;
  if (request.destination === 'worker') return false;
  return request.destination === 'font' || request.destination === 'image' || /\/assets\//.test(url.pathname);
};
