/**
 * PWA manifest test — verifies the generated ``dist/manifest.webmanifest``
 * has the fields required by an installable PWA and that they match
 * the values we declared in ``vite.config.ts``.
 *
 * This runs against the BUILD OUTPUT, and an absent build fails it rather
 * than skipping it. The previous shape was ``describe.skipIf(!hasBuild)``
 * over ``readFileSync(MANIFEST) : '{}'``, which meant an unbuilt tree
 * parsed an empty object, asserted nothing, and reported green - a result
 * indistinguishable from a manifest that carries every field. ``dist/`` is
 * gitignored and nothing in this suite builds it, so that was the ordinary
 * state of this file, not a corner case.
 *
 * See service-worker.test.ts for who pays the build these tests need.
 */
import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const DIST = resolve(__dirname, '..', '..', 'dist');
const MANIFEST = resolve(DIST, 'manifest.webmanifest');

let cached: Record<string, unknown> | null = null;

function manifestJson(): Record<string, unknown> {
  if (cached === null) {
    if (!existsSync(MANIFEST)) {
      throw new Error(
        `No build output to inspect: ${MANIFEST} does not exist.\n` +
          'These tests read the build output, so run `npm run build` in frontend/ ' +
          'before them. This is a failure rather than a skip on purpose: a ' +
          'build-output test that skips itself reports green without having read ' +
          'anything, and nobody can tell that apart from a clean result.',
      );
    }
    cached = JSON.parse(readFileSync(MANIFEST, 'utf-8')) as Record<string, unknown>;
  }
  return cached;
}

describe('PWA manifest', () => {
  it('has the required identity fields', () => {
    const manifest = manifestJson();
    expect(manifest.name).toBe('OpenConstructionERP');
    expect(manifest.short_name).toBe('OCERP');
    expect(typeof manifest.description).toBe('string');
  });

  it('sets the OCE theme palette', () => {
    const manifest = manifestJson();
    expect(manifest.theme_color).toBe('#2987F8');
    expect(manifest.background_color).toBe('#F0EEEB');
  });

  it('declares display=standalone and the root scope', () => {
    const manifest = manifestJson();
    expect(manifest.display).toBe('standalone');
    expect(manifest.start_url).toBe('/');
    expect(manifest.scope).toBe('/');
  });

  it('ships icons in 192/256/384/512 + a maskable variant', () => {
    const icons = manifestJson().icons as Array<{ src: string; sizes: string; purpose?: string }>;
    expect(Array.isArray(icons)).toBe(true);

    const sizes = icons.map((i) => i.sizes);
    expect(sizes).toContain('192x192');
    expect(sizes).toContain('256x256');
    expect(sizes).toContain('384x384');
    expect(sizes).toContain('512x512');

    const maskable = icons.find((i) => (i.purpose ?? '').includes('maskable'));
    expect(maskable, 'manifest must include a maskable icon for adaptive launchers').toBeTruthy();

    // Raster icons live under /pwa/, the scalable brand mark under /brand/erp/.
    for (const icon of icons) {
      expect(icon.src.startsWith('/pwa/') || icon.src.startsWith('/brand/erp/')).toBe(true);
    }
  });
});

// Always-on assertion: this one reads the source config, so it answers
// before a build too. It is what catches somebody dropping the PWA plugin
// from vite.config.ts, which the build-output half above would report as a
// missing file rather than as a removed plugin.
describe('PWA plugin configuration', () => {
  it('vite.config.ts still wires VitePWA with the OCERP manifest', () => {
    const config = readFileSync(resolve(__dirname, '..', '..', 'vite.config.ts'), 'utf-8');
    expect(config).toContain('VitePWA');
    expect(config).toContain("'OpenConstructionERP'");
    expect(config).toContain("'OCERP'");
    expect(config).toContain("'#2987F8'");
  });
});
