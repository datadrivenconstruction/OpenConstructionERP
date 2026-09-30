/**
 * PWA service-worker test — verifies the generated ``dist/sw.js``
 * registers the three runtime cache lanes declared in vite.config.ts:
 *   * oce-static-assets-v2 (CacheFirst, same-origin fonts/images/asset chunks)
 *   * oce-i18n-locales    (StaleWhileRevalidate, per-locale chunks)
 *   * oce-api             (NetworkFirst, /api/v1/* GETs)
 *
 * AN ABSENT BUILD IS A FAILURE HERE, NOT A SKIP, and that is the whole
 * point of this file's shape. It used to open with
 * ``describe.skipIf(!hasBuild)``, so on any tree that had not been built
 * the file reported green having read nothing at all. ``dist/`` is
 * gitignored and nothing in this suite builds it, so that was the normal
 * state rather than an edge case. A reader who sees green takes it to
 * mean "the lanes are there"; what it really meant was "the file was
 * never opened", and those two answers must not be able to look alike.
 *
 * The artifact is deliberately NOT generated here on the fly from the
 * config. What is being asked about is the file a visitor's browser
 * downloads, and ``public/sw.js`` is copied verbatim onto this same path
 * during a build - so a test that generated its own copy out of
 * vite.config.ts would go green over precisely the collision that would
 * hurt, while proving only that workbox-build still works.
 *
 * Cost, and who pays it: reading build output means these tests need a
 * build in front of them. ci.yml's macOS runner skips the build on
 * purpose (a 9 GB heap does not fit a 7 GB runner), so that lane excludes
 * this directory by name. The exclusion is written where a reader can see
 * it instead of being hidden inside a test that reports green with
 * nothing to read.
 */
import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { STATIC_ASSETS_CACHE } from '../../src/pwa/staticAssetRoute';

const DIST = resolve(__dirname, '..', '..', 'dist');
const SW = resolve(DIST, 'sw.js');

let cached: string | null = null;

function serviceWorkerSource(): string {
  if (cached === null) {
    if (!existsSync(SW)) {
      throw new Error(
        `No build output to inspect: ${SW} does not exist.\n` +
          'These tests read the build output, so run `npm run build` in frontend/ ' +
          'before them. This is a failure rather than a skip on purpose: a ' +
          'build-output test that skips itself reports green without having read ' +
          'anything, and nobody can tell that apart from a clean result.',
      );
    }
    cached = readFileSync(SW, 'utf-8');
  }
  return cached;
}

describe('PWA service worker (generateSW)', () => {
  it('is emitted by the build', () => {
    // Named as its own case so the first thing a reader sees on an unbuilt
    // tree is "there is no build output" rather than "oce-api is missing
    // from an empty string". The assertion is the existence of the file,
    // not its length: a length check passes on anything non-empty and so
    // says nothing on its own.
    expect(existsSync(SW), `${SW} was not emitted by the build`).toBe(true);
  });

  it('is a workbox service worker', () => {
    // workbox-build emits an importScripts()/define() call naming the
    // workbox-*.js runtime it ships beside sw.js. This is a real question
    // about which file ended up on this path, not a formality: a
    // hand-written service worker landing here from public/ would satisfy
    // every "the file exists" check and mention workbox nowhere. The
    // assertion this replaces read `... || sw.length > 0`, which no
    // non-empty file on earth could fail.
    expect(serviceWorkerSource()).toMatch(/workbox/i);
  });

  it('declares the oce-static-assets runtime cache', () => {
    expect(serviceWorkerSource()).toContain(STATIC_ASSETS_CACHE);
  });

  it('carries the same-origin guard into the static assets lane', () => {
    // workbox copies the match callback into sw.js as source text. If the
    // import were lost on the way, the lane would be matching something
    // else, and cross-origin covers would be cached again.
    expect(serviceWorkerSource()).toContain('sameOrigin');
  });

  it('declares the oce-i18n-locales runtime cache', () => {
    expect(serviceWorkerSource()).toContain('oce-i18n-locales');
  });

  it('declares the oce-api runtime cache', () => {
    expect(serviceWorkerSource()).toContain('oce-api');
  });

  it('declares the navigation fallback to /index.html', () => {
    // workbox-build emits this as a NavigationRoute mounted with the
    // index.html document. Match either textual marker that workbox
    // produces for it.
    const sw = serviceWorkerSource();
    expect(sw.includes('index.html') || sw.includes('NavigationRoute')).toBe(true);
  });

  it('enables clientsClaim + skipWaiting for autoUpdate strategy', () => {
    const sw = serviceWorkerSource();
    expect(sw.includes('clientsClaim') || sw.includes('claimClients')).toBe(true);
    expect(sw).toContain('skipWaiting');
  });
});

// Always-on guards: these read the source config rather than the build
// output, so they answer even before a build. They are not a substitute
// for the block above - a config can name the three lanes while the build
// output on disk is some other file entirely - which is why both halves
// are here.
describe('PWA service worker configuration', () => {
  const config = readFileSync(resolve(__dirname, '..', '..', 'vite.config.ts'), 'utf-8');

  it('configures oce-static-assets cache', () => {
    expect(STATIC_ASSETS_CACHE).toBe('oce-static-assets-v2');
    expect(config).toContain('cacheName: STATIC_ASSETS_CACHE');
    expect(config).toContain('urlPattern: isStaticAssetRequest');
  });

  it('configures oce-i18n-locales cache', () => {
    expect(config).toContain("'oce-i18n-locales'");
  });

  it('configures oce-api cache with NetworkFirst + 30s timeout', () => {
    expect(config).toContain("'oce-api'");
    expect(config).toContain("'NetworkFirst'");
    expect(config).toContain('networkTimeoutSeconds: 30');
  });

  it('configures registerType: autoUpdate', () => {
    expect(config).toContain("registerType: 'autoUpdate'");
  });
});
