// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The service worker's CacheFirst lane takes same-origin static files only.
 *
 * It used to take every image including cross-origin ones and cache status 0,
 * so an opaque 404 from the video thumbnail host was stored as a success and
 * served for 30 days. These cases pin the narrower rule and the recovery path
 * for browsers that still hold the old cache.
 *
 * Run: npx vitest run src/pwa/__tests__/staticAssetRoute.test.ts
 */
import { describe, expect, it, vi } from 'vitest';

import { retireStaleCaches } from '../retireStaleCaches';
import {
  RETIRED_STATIC_ASSETS_CACHES,
  STATIC_ASSETS_CACHE,
  isStaticAssetRequest,
} from '../staticAssetRoute';

const ORIGIN = 'https://app.example.org';

function match(href: string, destination: string): boolean {
  const url = new URL(href, ORIGIN);
  return isStaticAssetRequest({ url, request: { destination }, sameOrigin: url.origin === ORIGIN });
}

describe('isStaticAssetRequest', () => {
  it('leaves cross-origin images to the browser cache', () => {
    expect(match('https://i.ytimg.com/vi/abc/maxresdefault.jpg', 'image')).toBe(false);
    expect(match('https://i.ytimg.com/vi/abc/hqdefault.jpg', 'image')).toBe(false);
    expect(match('https://openconstructionerp.com/uberization-of-construction/img/og-en.jpg', 'image')).toBe(false);
    expect(match('https://fonts.gstatic.com/s/inter/v1/x.woff2', 'font')).toBe(false);
    expect(match('https://cdn.example.net/assets/x.js', 'script')).toBe(false);
  });

  it('handles same-origin hashed assets, fonts and images', () => {
    expect(match('/assets/index-3f9a1c.js', 'script')).toBe(true);
    expect(match('/assets/inter-latin-400.woff2', 'font')).toBe(true);
    expect(match('/assets/videos/academy/intro.webp', 'image')).toBe(true);
    expect(match('/brand/logo.svg', 'image')).toBe(true);
    // The /demo deployment keeps its prefix in the browser URL.
    expect(match('/demo/assets/index-3f9a1c.js', 'script')).toBe(true);
  });

  it('never takes the API or a worker script', () => {
    expect(match('/api/v1/documents/photos/1/thumb/', 'image')).toBe(false);
    expect(match('/assets/pdf.worker.min-1a2b.mjs', 'worker')).toBe(false);
    expect(match('/index.html', 'document')).toBe(false);
  });

  it('is self-contained, because workbox copies it into sw.js as source text', () => {
    const source = isStaticAssetRequest.toString();
    expect(source).toContain('sameOrigin');
    expect(source).not.toMatch(/\bimport\b|STATIC_ASSETS_CACHE|RETIRED_/);
  });
});

describe('the renamed cache', () => {
  it('leaves the old name behind', () => {
    expect(STATIC_ASSETS_CACHE).toBe('oce-static-assets-v2');
    expect(RETIRED_STATIC_ASSETS_CACHES).toContain('oce-static-assets');
    expect(RETIRED_STATIC_ASSETS_CACHES).not.toContain(STATIC_ASSETS_CACHE);
  });

  it('deletes the old cache on start', async () => {
    const storage = { delete: vi.fn(async (name: string) => name === 'oce-static-assets') };
    expect(await retireStaleCaches(storage)).toEqual(['oce-static-assets']);
    expect(storage.delete).toHaveBeenCalledWith('oce-static-assets');
    expect(storage.delete).not.toHaveBeenCalledWith(STATIC_ASSETS_CACHE);
  });

  it('never throws when Cache Storage is missing or refuses', async () => {
    expect(await retireStaleCaches(undefined)).toEqual([]);
    const refusing = {
      delete: vi.fn(async (_name: string): Promise<boolean> => {
        throw new DOMException('blocked', 'SecurityError');
      }),
    };
    await expect(retireStaleCaches(refusing)).resolves.toEqual([]);
  });
});
