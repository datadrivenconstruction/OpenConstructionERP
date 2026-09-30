// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The 3D globe shows relief unless the operator configured raster streets.
 *
 * The globe can only draw raster XYZ imagery and no keyless public raster
 * street service permits app use, so relief is the default. An operator who
 * sets OE_GLOBE_STREET_TILES_URL with its attribution gets streets, served
 * through our own origin with the provider's credit. Every other answer,
 * including a failed or malformed one, must still leave the globe with a
 * picture, which is why the fallback is asserted as hard as the opt-in.
 *
 * Run: npx vitest run src/shared/ui/ProjectMap/__tests__/globeImagery.test.ts
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  GLOBE_IMAGERY_CONFIG_URL,
  PROXY_TILE_URL,
  RELIEF_ATTRIBUTION,
  RELIEF_GLOBE_IMAGERY,
  RELIEF_MAX_ZOOM,
  fetchGlobeImagery,
  resolveGlobeImagery,
} from '../basemap';

const STREETS = {
  streets: {
    tile_url: '/api/v1/geo-hub/globe-streets/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
    max_zoom: 18,
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('resolveGlobeImagery', () => {
  it('keeps relief when nothing is configured', () => {
    expect(RELIEF_GLOBE_IMAGERY).toEqual({
      url: PROXY_TILE_URL,
      credit: RELIEF_ATTRIBUTION,
      maxZoom: RELIEF_MAX_ZOOM,
      streets: false,
    });
    expect(resolveGlobeImagery({ streets: null })).toBe(RELIEF_GLOBE_IMAGERY);
    expect(resolveGlobeImagery({})).toBe(RELIEF_GLOBE_IMAGERY);
    expect(resolveGlobeImagery(null)).toBe(RELIEF_GLOBE_IMAGERY);
  });

  it('uses the configured street tiles with their credit', () => {
    expect(resolveGlobeImagery(STREETS)).toEqual({
      url: '/api/v1/geo-hub/globe-streets/{z}/{x}/{y}.png',
      credit: '© OpenStreetMap contributors',
      maxZoom: 18,
      streets: true,
    });
  });

  it('refuses an uncredited or off-origin source', () => {
    expect(resolveGlobeImagery({ streets: { ...STREETS.streets, attribution: ' ' } })).toBe(RELIEF_GLOBE_IMAGERY);
    expect(
      resolveGlobeImagery({ streets: { ...STREETS.streets, tile_url: 'https://tiles.example.org/{z}/{x}/{y}.png' } }),
    ).toBe(RELIEF_GLOBE_IMAGERY);
  });
});

describe('fetchGlobeImagery', () => {
  it('reads the backend answer', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(STREETS), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const imagery = await fetchGlobeImagery();
    expect(imagery.streets).toBe(true);
    expect(fetchMock.mock.calls[0]![0]).toBe(GLOBE_IMAGERY_CONFIG_URL);
  });

  it('falls back to relief when the backend fails or is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('no', { status: 500 })));
    expect(await fetchGlobeImagery()).toBe(RELIEF_GLOBE_IMAGERY);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('network');
      }),
    );
    expect(await fetchGlobeImagery()).toBe(RELIEF_GLOBE_IMAGERY);
  });
});

describe('both Cesium viewers draw the resolved imagery', () => {
  const SRC = resolve(__dirname, '../../../..');
  it.each(['features/geo-hub/CesiumViewer.tsx', 'features/geo-hub/hooks/useCesiumViewer.ts'])('%s', (rel) => {
    const code = readFileSync(resolve(SRC, rel), 'utf-8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\/\/.*$/gm, '');
    expect(code).toContain('fetchGlobeImagery');
    // A hardcoded relief source here would ignore the operator's setting.
    expect(code).not.toMatch(/\bPROXY_TILE_URL\b|\bRELIEF_ATTRIBUTION\b|\bRELIEF_MAX_ZOOM\b/);
    expect(code).toMatch(/url:\s*imagery\.url/);
    expect(code).toMatch(/credit:\s*imagery\.credit/);
  });
});
