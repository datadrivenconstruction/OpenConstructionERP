// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One-shot street-map snapshots for surfaces that cannot host a live map.
 *
 * WHY. The project list card used to paint a single shaded-relief raster
 * tile, because an ``<img>`` cannot consume vector tiles and the only
 * keyless raster basemap we have is Natural Earth relief, which stops at
 * z6 and has no streets at any zoom. A construction user looking at a
 * project card wants the site: streets, roads, building footprints. A
 * country-scale terrain patch is not that.
 *
 * The obvious fix - mount MapLibre in every card - is the thing the card
 * variant exists to avoid. The grid renders about twelve cards at once, so
 * that is twelve WebGL contexts streaming vector tiles for as long as the
 * page is open, and the page never reaches network idle.
 *
 * So render the vector style ONCE into an offscreen map, read the canvas
 * as a data URL, and destroy the context. What survives is an image. One
 * transient context at a time, nothing streaming afterwards, and the
 * result is cached so a re-render or a revisit does not pay again.
 *
 * WHAT CAN GO WRONG, AND WHAT HAPPENS THEN. No WebGL, a blocked style, a
 * driver that refuses a context, a machine slow enough to miss the
 * timeout: every one of them resolves ``null``. Never a throw, never a
 * placeholder image. The caller keeps whatever it was already showing,
 * which is the relief tile, so a failure costs detail and never costs the
 * picture.
 */
import type { Map as MaplibreMap } from 'maplibre-gl';

import { VECTOR_BASEMAP_STYLE_URL } from './basemap';

export interface StreetThumbnailRequest {
  lat: number;
  lng: number;
  /** Web-Mercator zoom. See ``CARD_STREET_ZOOM`` in ProjectMap.tsx. */
  zoom: number;
  /** CSS pixels. The canvas is this times the effective pixel ratio. */
  width: number;
  height: number;
  /** Abort before the job reaches the front of the queue, or mid-render. */
  signal?: AbortSignal;
}

/**
 * Ceiling on the render scale.
 *
 * MapLibre sizes its canvas to ``container.clientWidth * pixelRatio``. Left
 * to ``devicePixelRatio`` a 3x display renders nine times the pixels of a
 * 1x one and the data URL grows with them, which is a cache the browser
 * then refuses to store. Two is the point past which the extra pixels stop
 * being visible in a 112 px tall thumbnail.
 */
const MAX_PIXEL_RATIO = 2;

/**
 * How long one snapshot may take before we give up on it.
 *
 * Generous on purpose: this runs behind a fallback that is already on
 * screen, so a slow render costs nobody anything, while a tight budget on
 * a cold tile cache would turn a working map into a permanent terrain
 * patch. The consecutive-failure brake below is what keeps a genuinely
 * broken environment from spending this budget twelve times over.
 *
 * For scale, six European cities rendered cold through this exact path on
 * a software rasteriser - no GPU at all, the slowest thing a real user
 * could be on - reached idle in 1.2 to 2.7 seconds. Twelve seconds is
 * roughly four times the worst of that, which is the margin wanted: the
 * cost of being wrong on the low side is a permanent terrain patch, and
 * the cost of being wrong on the high side is background work nobody is
 * waiting on.
 */
const RENDER_TIMEOUT_MS = 12_000;

/**
 * After this many consecutive failures, stop trying for the rest of the
 * page session.
 *
 * The failure modes here are environmental rather than per-request: no
 * WebGL, a style endpoint that is not answering, a blocked origin. All of
 * them fail identically for every card, so without a brake a list of
 * twelve cards would sit through twelve full timeouts to learn the same
 * thing twelve times. Two rather than one because a single timeout can
 * genuinely be a slow first tile fetch.
 */
const FAILURE_LIMIT = 2;

const SESSION_CACHE_PREFIX = 'oe.streetmap.';

/**
 * In-memory cache, consulted before session storage.
 *
 * Session storage is the durable half and survives a route change; this
 * half exists because a React list re-renders far more often than it
 * navigates, and pulling a quarter-megabyte data URL out of storage on
 * every render is work nobody asked for.
 *
 * "Durable" is relative, and the limit is low enough to plan around: see
 * the quota note in ``writeSessionCache``. Past roughly eight cards the
 * durable half stops accepting entries and this one is the whole cache.
 */
const memoryCache = new Map<string, string>();

/** Serialises every render. See ``enqueue``. */
let queueTail: Promise<void> = Promise.resolve();

let consecutiveFailures = 0;

/** Rounded so two cards a few metres apart share one snapshot. */
function roundCoord(v: number): string {
  // Four decimals is about 11 m at the equator, comfortably finer than the
  // geocoder's own precision and far coarser than the float noise that
  // would otherwise give every card its own cache entry.
  return v.toFixed(4);
}

/** Effective render scale for this display, after the ceiling above. */
export function effectivePixelRatio(): number {
  const raw = typeof window === 'undefined' ? 1 : window.devicePixelRatio;
  if (!Number.isFinite(raw) || (raw as number) <= 0) return 1;
  return Math.min(MAX_PIXEL_RATIO, raw as number);
}

/**
 * Cache key.
 *
 * Carries the pixel size and the EFFECTIVE ratio rather than
 * ``devicePixelRatio``: the effective one is what the canvas was actually
 * rendered at, and keying on the raw value would hand a 3x display a miss
 * for an image it would have rendered identically.
 */
export function thumbnailCacheKey(opts: Omit<StreetThumbnailRequest, 'signal'>): string {
  const w = Math.max(1, Math.round(opts.width));
  const h = Math.max(1, Math.round(opts.height));
  return `${roundCoord(opts.lat)},${roundCoord(opts.lng)}@${opts.zoom}/${w}x${h}@${effectivePixelRatio()}`;
}

function readSessionCache(key: string): string | null {
  try {
    return sessionStorage.getItem(SESSION_CACHE_PREFIX + key);
  } catch {
    // Storage throws outright in a few contexts (private modes, embedded
    // views, site-data blocking). A cache that cannot be read is not an
    // error, it is a cache miss.
    return null;
  }
}

function writeSessionCache(key: string, dataUrl: string) {
  try {
    sessionStorage.setItem(SESSION_CACHE_PREFIX + key, dataUrl);
  } catch {
    // Quota, and expect it on a full grid rather than treating it as
    // exotic. Measured, these snapshots are about 260 KB of base64 each,
    // and browsers hold strings as UTF-16, so one entry costs roughly
    // 520 KB of a quota that is commonly 5 MB. A twelve-card page therefore
    // fills session storage somewhere around the eighth card and every
    // later write lands here.
    //
    // That is degradation, not breakage, and deliberately not worth code:
    // the snapshot is already rendered and about to be shown, the
    // in-memory half still covers re-renders for the life of the page, and
    // the only cost is that the last few cards render again on a revisit.
  }
}

/** Drops both cache halves and the failure brake. Used by tests. */
export function resetStreetThumbnailCache() {
  memoryCache.clear();
  consecutiveFailures = 0;
  try {
    const doomed: string[] = [];
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const key = sessionStorage.key(i);
      if (key && key.startsWith(SESSION_CACHE_PREFIX)) doomed.push(key);
    }
    for (const key of doomed) sessionStorage.removeItem(key);
  } catch {
    /* nothing to drop if storage is unreadable */
  }
}

/**
 * Runs jobs one at a time, in call order.
 *
 * The whole point of this module is that twelve cards never hold twelve GL
 * contexts, and "one at a time" has to hold even transiently: twelve
 * contexts opened and closed in the same tick is still twelve contexts,
 * and a browser that caps them silently loses the excess. The tail is
 * advanced through a handler on BOTH settlement paths so one rejected job
 * cannot wedge the queue.
 */
function enqueue<T>(job: () => Promise<T>): Promise<T> {
  const result = queueTail.then(job, job);
  queueTail = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

function aborted(signal?: AbortSignal): boolean {
  return signal?.aborted === true;
}

/** Resolves true once the map has finished drawing, false on give-up. */
function waitForIdle(map: MaplibreMap, signal?: AbortSignal): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    let settled = false;
    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      map.off('idle', onIdle);
      signal?.removeEventListener('abort', onAbort);
      resolve(ok);
    };
    const onIdle = () => finish(true);
    const onAbort = () => finish(false);
    const timer = setTimeout(() => finish(false), RENDER_TIMEOUT_MS);
    map.on('idle', onIdle);
    signal?.addEventListener('abort', onAbort);
  });
}

async function renderOnce(opts: StreetThumbnailRequest): Promise<string | null> {
  const { lat, lng, zoom, signal } = opts;
  const width = Math.max(1, Math.round(opts.width));
  const height = Math.max(1, Math.round(opts.height));

  let container: HTMLDivElement | null = null;
  let map: MaplibreMap | null = null;
  try {
    // Imported here rather than at module scope so a page that never
    // renders a thumbnail never pays for the library, and so a failure to
    // load it is just another null.
    const maplibregl = (await import('maplibre-gl')).default;
    if (aborted(signal)) return null;

    // ATTACHED, not detached, and deliberately not display:none. MapLibre
    // sizes its canvas to ``container.clientWidth * pixelRatio``, and an
    // element outside the document - or hidden - measures zero, so the
    // snapshot comes back blank however correct the rest of this is.
    // Parked off-screen instead, which measures normally.
    container = document.createElement('div');
    container.setAttribute('aria-hidden', 'true');
    container.style.position = 'absolute';
    container.style.left = '-10000px';
    container.style.top = '0';
    container.style.width = `${width}px`;
    container.style.height = `${height}px`;
    container.style.pointerEvents = 'none';
    document.body.appendChild(container);

    map = new maplibregl.Map({
      container,
      style: VECTOR_BASEMAP_STYLE_URL,
      center: [lng, lat],
      zoom,
      interactive: false,
      // The credit belongs in the DOM next to the image, not baked into
      // the bitmap: text in a cached PNG cannot be selected, read by a
      // screen reader or followed, and it would be duplicated by the
      // chrome the consumer draws anyway.
      attributionControl: false,
      pixelRatio: effectivePixelRatio(),
      // maplibre-gl 5 moved the WebGL context flags here from the top
      // level, and the move is silent: passing preserveDrawingBuffer as a
      // top-level option is simply not read. Measured on the context itself
      // rather than on the options object, because the options object is
      // what lies - top level gives
      // ``gl.getContextAttributes().preserveDrawingBuffer === false``, here
      // gives true.
      //
      // Do not conclude from a working local render that the flag is
      // optional. With it false the spec lets the browser clear the drawing
      // buffer once the frame is composited, after which toDataURL returns a
      // blank image; whether it does is up to the driver. A headless
      // SwiftShader run here returned a byte-identical picture either way,
      // which proves only that this driver keeps the buffer, not that the
      // flag is unnecessary.
      canvasContextAttributes: { preserveDrawingBuffer: true },
      fadeDuration: 0,
    });

    const ready = await waitForIdle(map, signal);
    if (!ready || aborted(signal)) return null;

    const dataUrl = map.getCanvas().toDataURL('image/png');
    // A canvas that never got a context stringifies to the 1x1 data URL
    // below. Treat that as a failure rather than caching a blank square
    // forever.
    if (!dataUrl || dataUrl.length < 128) return null;
    return dataUrl;
  } catch {
    return null;
  } finally {
    try {
      map?.remove();
    } catch {
      /* removing a map that never finished constructing can throw */
    }
    container?.remove();
  }
}

/**
 * Renders a street-cartography snapshot of one location.
 *
 * Resolves a PNG data URL, or ``null`` when the environment cannot produce
 * one. Callers must treat null as "keep showing what you have".
 */
export async function renderStreetThumbnail(
  opts: StreetThumbnailRequest,
): Promise<string | null> {
  if (typeof document === 'undefined' || typeof window === 'undefined') return null;
  if (!Number.isFinite(opts.lat) || !Number.isFinite(opts.lng)) return null;
  if (aborted(opts.signal)) return null;

  const key = thumbnailCacheKey(opts);
  const hot = memoryCache.get(key);
  if (hot) return hot;
  const stored = readSessionCache(key);
  if (stored) {
    memoryCache.set(key, stored);
    return stored;
  }

  if (consecutiveFailures >= FAILURE_LIMIT) return null;

  return enqueue(async () => {
    // Re-checked inside the job rather than only at the door. A card that
    // was filtered away while its turn was still queued must not open a
    // context, and by the time the queue reaches it the cache may also
    // have been filled by an identical neighbouring card.
    if (aborted(opts.signal)) return null;
    const cached = memoryCache.get(key);
    if (cached) return cached;
    if (consecutiveFailures >= FAILURE_LIMIT) return null;

    const dataUrl = await renderOnce(opts);
    if (!dataUrl) {
      // An abort is a cancelled job, not a broken environment, so it must
      // not count towards the brake or one filter click would disable
      // thumbnails for the rest of the session.
      if (!aborted(opts.signal)) consecutiveFailures += 1;
      return null;
    }
    consecutiveFailures = 0;
    memoryCache.set(key, dataUrl);
    writeSessionCache(key, dataUrl);
    return dataUrl;
  });
}
