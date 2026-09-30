// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';
import type { ImgHTMLAttributes, ReactNode } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';

export interface AuthImageProps
  extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'> {
  /**
   * Image URL. A same-origin API path (``/api/...``) is fetched with the
   * bearer token; anything else (``data:``, ``blob:``, a static asset, an
   * external host) is handed to the ``<img>`` as it is.
   */
  src: string;
  /** Rendered while the blob is being fetched. */
  placeholder?: ReactNode;
  /** Rendered when the image cannot be loaded (401, 404, network, decode). */
  fallback?: ReactNode;
}

/**
 * Whether a URL is one of our own bearer-protected API endpoints.
 *
 * Only these need the token. Sending it anywhere else would leak it to a
 * third party, and fetching a ``data:`` or external URL through ``fetch``
 * trades a working ``<img>`` for a CORS failure.
 */
export function isAuthAssetUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  if (url.startsWith('/api/')) return true;
  if (typeof window === 'undefined') return false;
  return url.startsWith(`${window.location.origin}/api/`);
}

/**
 * How long an object URL outlives its last reader.
 *
 * A list that re-renders, a tab switch, a lightbox opening the image the grid
 * already showed: all of them release and re-acquire the same URL within a
 * moment. Keeping the blob briefly turns each of those into a cache hit
 * instead of a second download, and still frees the memory soon after the
 * image really leaves the screen.
 */
const RELEASE_DELAY_MS = 30_000;

interface CacheEntry {
  promise: Promise<string>;
  objectUrl: string | null;
  refs: number;
  timer: ReturnType<typeof setTimeout> | null;
}

/** One entry per image URL, shared by every component showing it. */
const cache = new Map<string, CacheEntry>();

async function fetchObjectUrl(src: string): Promise<string> {
  const token = useAuthStore.getState().accessToken;
  const headers: Record<string, string> = { Accept: 'image/*' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(src, { headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return URL.createObjectURL(await res.blob());
}

function acquire(src: string): CacheEntry {
  let entry = cache.get(src);
  if (!entry) {
    const fresh: CacheEntry = { promise: Promise.resolve(''), objectUrl: null, refs: 0, timer: null };
    fresh.promise = fetchObjectUrl(src).then(
      (url) => {
        fresh.objectUrl = url;
        return url;
      },
      (err: unknown) => {
        // A failure is not cached: the next mount must be able to retry,
        // for example after the token was refreshed.
        if (cache.get(src) === fresh) cache.delete(src);
        throw err;
      },
    );
    cache.set(src, fresh);
    entry = fresh;
  }
  if (entry.timer) {
    clearTimeout(entry.timer);
    entry.timer = null;
  }
  entry.refs += 1;
  return entry;
}

function release(src: string, entry: CacheEntry) {
  entry.refs = Math.max(0, entry.refs - 1);
  if (entry.refs > 0 || entry.timer) return;
  entry.timer = setTimeout(() => {
    entry.timer = null;
    if (entry.refs > 0) return;
    if (cache.get(src) === entry) cache.delete(src);
    if (entry.objectUrl) URL.revokeObjectURL(entry.objectUrl);
  }, RELEASE_DELAY_MS);
}

/** Drops every cached blob. For tests. */
export function resetAuthImageCache() {
  for (const entry of cache.values()) {
    if (entry.timer) clearTimeout(entry.timer);
    if (entry.objectUrl) URL.revokeObjectURL(entry.objectUrl);
  }
  cache.clear();
}

export interface AuthedObjectUrl {
  /** Something an ``<img>``, a texture loader or a new tab can load. */
  url: string | null;
  /** The protected fetch failed (401, 404, network). */
  failed: boolean;
}

/**
 * Resolve an image URL into one that loads without an ``Authorization``
 * header.
 *
 * ``<img src>``, ``background-image``, three.js ``TextureLoader`` and a new
 * tab all request the URL themselves and never send our bearer token, so a
 * protected endpoint answers 401 and the picture is broken. For those URLs
 * this fetches with the token and returns an object URL; every other URL is
 * returned unchanged. The token never goes into the URL.
 */
export function useAuthedObjectUrl(src: string | null | undefined): AuthedObjectUrl {
  const needsAuth = isAuthAssetUrl(src);
  const [state, setState] = useState<AuthedObjectUrl>(() => {
    if (!src) return { url: null, failed: false };
    if (!needsAuth) return { url: src, failed: false };
    const hit = cache.get(src);
    return { url: hit?.objectUrl ?? null, failed: false };
  });

  useEffect(() => {
    if (!src) {
      setState({ url: null, failed: false });
      return undefined;
    }
    if (!needsAuth) {
      setState({ url: src, failed: false });
      return undefined;
    }
    let live = true;
    const entry = acquire(src);
    setState({ url: entry.objectUrl, failed: false });
    entry.promise.then(
      (url) => {
        if (live) setState({ url, failed: false });
      },
      () => {
        if (live) setState({ url: null, failed: true });
      },
    );
    return () => {
      live = false;
      release(src, entry);
    };
  }, [src, needsAuth]);

  return state;
}

/**
 * ``<img>`` that works for every image URL the platform stores.
 *
 * Protected API images are fetched with the bearer token (see
 * ``useAuthedObjectUrl``) and shared through a small cache; public URLs are
 * loaded directly. Either way a URL that does not produce a picture shows
 * ``fallback`` rather than the browser's broken-image icon.
 */
export function AuthImage({
  src,
  placeholder = null,
  fallback = null,
  onError,
  ...imgProps
}: AuthImageProps) {
  const { url, failed } = useAuthedObjectUrl(src);
  const [broken, setBroken] = useState(false);

  useEffect(() => {
    setBroken(false);
  }, [url]);

  if (failed || broken) return <>{fallback}</>;
  if (!url) return <>{placeholder}</>;
  // A11y: every <img> needs an alt attribute. Callers that pass `alt`
  // win via {...imgProps}; we fall back to an empty alt (decorative)
  // so the rendered <img> always has the attribute present.
  return (
    <img
      alt=""
      {...imgProps}
      src={url}
      onError={(event) => {
        setBroken(true);
        onError?.(event);
      }}
    />
  );
}
