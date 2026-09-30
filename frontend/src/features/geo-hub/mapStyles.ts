// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Basemap styles for the lightweight 2D Geo Hub map (MapLibre GL).
 *
 * The Geo Hub ships two rendering engines:
 *
 *   * the 3D globe (Cesium) - rich, heavy (~3 MB runtime), best for
 *     terrain + 3D tilesets;
 *   * this 2D map (MapLibre GL) - light, instant, "like paper", best for
 *     quickly placing projects and drawings on a clear, readable map.
 *
 * Every style here is fully open-source and self-hostable:
 *
 *   * ``streets`` / ``minimal`` are vector styles served by our OWN
 *     same-origin backend (see ``shared/ui/ProjectMap/basemap``), which
 *     vendors them with every URL - tiles, glyphs, sprite - pointed back at
 *     itself and fetches the OpenStreetMap-derived OpenFreeMap vector tiles
 *     server-side. No external CDN at runtime, no API key, works behind
 *     ad/privacy blockers.
 *   * ``paper`` / ``blueprint`` use NO tiles at all - just a flat drawn
 *     background. They render fully offline (air-gapped / no internet) and
 *     give the clean "drawing on paper" canvas for placing projects and
 *     georeferenced drawings. Nothing leaves the browser.
 *
 * Switching a basemap is a single MapLibre ``setStyle`` (or a React
 * ``mapStyle`` prop swap) - instant, no reload.
 */
import type { StyleSpecification } from 'maplibre-gl';

import { basemapStyleUrl, streetBasemapStyleUrl } from '@/shared/ui/ProjectMap/basemap';

/** Identifier for each selectable basemap. */
export type BasemapId = 'streets' | 'minimal' | 'paper' | 'blueprint';

/** Default basemap for a fresh 2D session - the readable full-colour map. */
export const DEFAULT_BASEMAP: BasemapId = 'streets';

/** localStorage key persisting the user's basemap choice across reloads. */
export const BASEMAP_LS_KEY = 'geoHub.basemap';

/**
 * Lucide icon name (resolved by the picker) + i18n metadata for each
 * basemap. Kept as data so the picker stays a thin presentational list.
 */
export interface BasemapMeta {
  id: BasemapId;
  /** Lucide icon name rendered by the picker. */
  icon: 'Map' | 'Layers' | 'FileText' | 'Grid3x3';
  labelKey: string;
  labelDefault: string;
  descKey: string;
  descDefault: string;
  /** ``true`` for the tile-free, fully-offline drawn backgrounds. */
  offline: boolean;
  /** Whether pins/labels should render in a light treatment (dark bg). */
  dark: boolean;
}

export const BASEMAPS = [
  {
    id: 'streets',
    icon: 'Map',
    labelKey: 'geo.basemap.streets',
    labelDefault: 'Streets',
    descKey: 'geo.basemap.streets_hint',
    descDefault: 'Full-colour street map (OpenStreetMap / OpenFreeMap).',
    offline: false,
    dark: false,
  },
  {
    id: 'minimal',
    icon: 'Layers',
    labelKey: 'geo.basemap.minimal',
    labelDefault: 'Minimal',
    descKey: 'geo.basemap.minimal_hint',
    descDefault: 'Light, desaturated map - less clutter, easy to read.',
    offline: false,
    dark: false,
  },
  {
    id: 'paper',
    icon: 'FileText',
    labelKey: 'geo.basemap.paper',
    labelDefault: 'Paper',
    descKey: 'geo.basemap.paper_hint',
    descDefault: 'Plain paper canvas - no tiles, works fully offline.',
    offline: true,
    dark: false,
  },
  {
    id: 'blueprint',
    icon: 'Grid3x3',
    labelKey: 'geo.basemap.blueprint',
    labelDefault: 'Blueprint',
    descKey: 'geo.basemap.blueprint_hint',
    descDefault: 'Dark drafting canvas - no tiles, works fully offline.',
    offline: true,
    dark: true,
  },
] as const satisfies readonly BasemapMeta[];

export function basemapMeta(id: BasemapId): BasemapMeta {
  return BASEMAPS.find((b) => b.id === id) ?? BASEMAPS[0];
}

/** Read the persisted basemap choice (SSR / quota safe). */
export function readBasemap(): BasemapId {
  if (typeof window === 'undefined') return DEFAULT_BASEMAP;
  try {
    const v = window.localStorage.getItem(BASEMAP_LS_KEY);
    if (v === 'streets' || v === 'minimal' || v === 'paper' || v === 'blueprint') {
      return v;
    }
  } catch {
    /* localStorage disabled / quota - fall through to default */
  }
  return DEFAULT_BASEMAP;
}

// ── Style builders ───────────────────────────────────────────────────────

/**
 * Vector basemap served by the same-origin backend. ``streets`` is the
 * full-colour cartography; ``minimal`` is a light, desaturated one.
 *
 * These used to be one raster source with MapLibre ``raster-saturation``
 * paint faking the "minimal" look. Vector gives each its own real
 * cartography instead of a filter over the other, and the labels come from
 * the style's glyphs rather than being burnt into the tile.
 */
function vectorStyle(variant: 'streets' | 'minimal', theme: 'light' | 'dark'): string {
  // Only ``streets`` follows the app theme: a full-colour light map is the
  // brightest thing on a dark screen. ``minimal`` stays the light,
  // desaturated map its picker entry promises, so the two tabs never show
  // the same picture.
  if (variant === 'minimal') return basemapStyleUrl('positron');
  return streetBasemapStyleUrl(theme);
}

/**
 * Tile-free background-only style. Renders fully offline - no network
 * request ever leaves the browser. Projects and georeferenced drawings
 * are painted on top by the viewer as markers and image layers, giving a
 * clean "drawing on paper" canvas.
 */
function flatStyle(background: string): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: 'oe-bg',
        type: 'background',
        paint: { 'background-color': background },
      },
    ],
  };
}

/** Background colour for the tile-free styles - reused by the viewer so
 *  the map container matches the canvas before MapLibre paints. */
export const BASEMAP_BACKDROP: Record<BasemapId, string> = {
  streets: '#e8eef3',
  minimal: '#f8fafc',
  paper: '#f4efe2',
  blueprint: '#0e2a47',
};

/** Container colour behind the dark street style, before MapLibre paints. */
export const DARK_STREETS_BACKDROP = '#0c0c0c';

/**
 * Build the MapLibre style for a basemap id. Cheap + pure, so callers can
 * call it inline in render and memoise on ``id`` alone.
 *
 * The tile-backed ids resolve to a style URL and the tile-free ones to an
 * inline style object; MapLibre's ``mapStyle`` accepts either.
 */
export function buildBasemapStyle(
  id: BasemapId,
  theme: 'light' | 'dark' = 'light',
): StyleSpecification | string {
  switch (id) {
    case 'minimal':
      return vectorStyle('minimal', theme);
    case 'paper':
      return flatStyle(BASEMAP_BACKDROP.paper);
    case 'blueprint':
      return flatStyle(BASEMAP_BACKDROP.blueprint);
    case 'streets':
    default:
      return vectorStyle('streets', theme);
  }
}
