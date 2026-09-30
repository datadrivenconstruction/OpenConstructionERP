// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Every map draws the shared street style, and that style is a street map.
 *
 * The founder reported the maps as terrain maps. The interactive maps were
 * already reading OpenFreeMap street tiles; what made them look like relief
 * was a shaded-relief raster the upstream styles blend in at low zoom, and a
 * project card that painted a relief tile while its street snapshot queued.
 * Both were fixed in one place each, which only holds while every map takes
 * its style from that one place. This file checks both halves:
 *
 *   1. the style config itself: street styles for light and dark, served
 *      from our own origin, dark picked by the dark theme;
 *   2. every file that constructs a MapLibre map gets its style from the
 *      shared module rather than from a URL of its own. A page that pasted a
 *      tile or style URL would keep working and silently drift from the fix.
 *
 * Run: npx vitest run src/tests/everyMapUsesTheSharedStreetStyle.test.ts
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import {
  DARK_VECTOR_BASEMAP_STYLE_URL,
  VECTOR_BASEMAP_STYLE_URL,
  basemapStyleUrl,
  streetBasemapStyleUrl,
} from '../shared/ui/ProjectMap/basemap';
import { buildBasemapStyle } from '../features/geo-hub/mapStyles';

const SRC = resolve(__dirname, '..');

/** The module that owns every basemap URL. */
const STYLE_MODULE = 'shared/ui/ProjectMap/basemap.ts';

/** A MapLibre consumer: imports the library or its React binding. */
const IMPORTS_MAPLIBRE = /from ['"](maplibre-gl|react-map-gl[^'"]*)['"]|import\(['"](maplibre-gl|react-map-gl[^'"]*)['"]\)/;

/** Any literal that would point a map at tiles or a style on its own. */
const OWN_TILE_SOURCE =
  /basemap-style\/|vector-tiles\/|tiles\.openfreemap|tile\.openstreetmap|opentopomap|arcgisonline|cartocdn|stamen|\{z\}\/\{x\}\/\{y\}/i;

/** What a ``mapStyle={...}`` or ``style: ...`` may be built from. */
const SHARED_STYLE_NAMES = [
  'streetStyleUrl',
  'buildBasemapStyle',
  'VECTOR_BASEMAP_STYLE_URL',
  'DARK_VECTOR_BASEMAP_STYLE_URL',
  'useStreetBasemapStyleUrl',
  'streetBasemapStyleUrl',
] as const;

function walk(dir: string, out: string[]) {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === 'locales' || name === '__tests__' || name === 'tests') continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      walk(full, out);
    } else if (/\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name)) {
      out.push(full);
    }
  }
}

function mapConsumers(): { rel: string; text: string }[] {
  const files: string[] = [];
  walk(SRC, files);
  return files
    .map((full) => ({ rel: relative(SRC, full).replace(/\\/g, '/'), text: readFileSync(full, 'utf-8') }))
    .filter(({ text }) => IMPORTS_MAPLIBRE.test(text));
}

const consumers = mapConsumers();

describe('the shared street style config', () => {
  it('serves light and dark street styles from our own origin', () => {
    expect(VECTOR_BASEMAP_STYLE_URL).toBe('/api/v1/geo-hub/basemap-style/liberty.json');
    expect(DARK_VECTOR_BASEMAP_STYLE_URL).toBe('/api/v1/geo-hub/basemap-style/dark.json');
    expect(basemapStyleUrl('positron')).toBe('/api/v1/geo-hub/basemap-style/positron.json');
  });

  it('picks the dark street style for the dark theme and liberty otherwise', () => {
    expect(streetBasemapStyleUrl('light')).toBe(VECTOR_BASEMAP_STYLE_URL);
    expect(streetBasemapStyleUrl('dark')).toBe(DARK_VECTOR_BASEMAP_STYLE_URL);
  });

  it('keeps the geo hub picker on the same street styles', () => {
    expect(buildBasemapStyle('streets')).toBe(VECTOR_BASEMAP_STYLE_URL);
    expect(buildBasemapStyle('streets', 'dark')).toBe(DARK_VECTOR_BASEMAP_STYLE_URL);
    expect(buildBasemapStyle('minimal')).toBe(basemapStyleUrl('positron'));
    expect(buildBasemapStyle('minimal', 'dark')).toBe(DARK_VECTOR_BASEMAP_STYLE_URL);
    // The drawn offline canvases carry no tiles in either theme.
    for (const id of ['paper', 'blueprint'] as const) {
      const style = buildBasemapStyle(id, 'dark');
      expect(typeof style).toBe('object');
      expect(JSON.stringify(style)).not.toMatch(OWN_TILE_SOURCE);
    }
  });
});

describe('every map takes its style from the shared module', () => {
  it('found the map components it claims to check', () => {
    const names = consumers.map((c) => c.rel);
    // Without this a moved directory would leave the loop below empty and green.
    expect(names).toContain('shared/ui/ProjectMap/ProjectMap.tsx');
    expect(names).toContain('features/dashboard/components/DashboardProjectsMap.tsx');
    expect(names).toContain('features/geo-hub/MapLibreViewer.tsx');
    expect(names).toContain('shared/ui/ProjectMap/streetThumbnail.ts');
  });

  it('no map component carries a tile or style URL of its own', () => {
    const offenders = consumers
      .filter(({ rel }) => rel !== STYLE_MODULE)
      .filter(({ text }) => {
        // Comments explain history and name old hosts; only code counts.
        const code = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
        return OWN_TILE_SOURCE.test(code);
      })
      .map(({ rel }) => rel);
    expect(
      offenders,
      `these map components name a tile or style URL directly instead of importing one from ${STYLE_MODULE}`,
    ).toEqual([]);
  });

  it.each(consumers.filter(({ text }) => /mapStyle=\{|\bstyle:\s*[A-Za-z_]/.test(text)))(
    '$rel builds its map style from the shared names',
    ({ rel, text }) => {
      const values = [
        ...[...text.matchAll(/mapStyle=\{([^}]+)\}/g)].map((m) => m[1]!.trim()),
        ...[...text.matchAll(/new Map\(\{[\s\S]*?\bstyle:\s*([^,\n]+)/g)].map((m) => m[1]!.trim()),
      ];
      expect(values.length, `${rel} passes a map style nobody could read`).toBeGreaterThan(0);
      for (const value of values) {
        const shared = SHARED_STYLE_NAMES.some((name) => value.startsWith(name));
        const derived = /^[a-z]\w*$/.test(value) && SHARED_STYLE_NAMES.some((name) => text.includes(name));
        expect(shared || derived, `${rel} passes mapStyle ${value}, which is not from ${STYLE_MODULE}`).toBe(
          true,
        );
      }
    },
  );
});
