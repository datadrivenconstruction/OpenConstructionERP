// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One style table for the screen and for print. Colours are `--oe-map-*`
 * CSS variables resolved at runtime (light and dark differ only there);
 * weights are px on screen and mm in print.
 */

import type { PlanLayerId, PlanStyleLayer } from './types';

export const MAP_TOKENS = [
  'bg', 'grid', 'grid-major', 'ink', 'ink-2', 'halo', 'accent', 'control-fill', 'topo', 'line', 'kerb', 'fence',
  'tree', 'utility', 'building', 'water', 'measure', 'misclosure', 'error', 'warning', 'success', 'surface',
  'breakline', 'parcel', 'zone', 'cut-3', 'cut-2', 'cut-1', 'neutral', 'fill-1', 'fill-2', 'fill-3',
] as const;
export type MapToken = (typeof MAP_TOKENS)[number];

/** Screen px -> print mm for the five line weights. */
export const LINE_WEIGHTS = { hair: [0.5, 0.13], thin: [1, 0.18], normal: [1.5, 0.25], bold: [2, 0.35], heavy: [3, 0.5] } as const;

export const FONT_REGULAR = ['Noto Sans Regular'];
export const FONT_BOLD = ['Noto Sans Bold'];
/** Glyphs served by our own origin (the geo hub proxy), so labels draw on the blank styles too. */
export const GLYPHS_URL = '/api/v1/geo-hub/fonts/{fontstack}/{range}.pbf';

const FALLBACK: Record<MapToken, string> = {
  bg: '#f7f6f2', grid: 'rgba(15,23,42,0.06)', 'grid-major': 'rgba(15,23,42,0.14)', ink: '#1d1d1f', 'ink-2': '#515154',
  halo: '#ffffff', accent: '#0071e3', 'control-fill': '#ffffff', topo: '#3a3a3c', line: '#3a3a3c', kerb: '#6e4b9e',
  fence: '#8a5a2b', tree: '#2f7d32', utility: '#0b6e99', building: '#7a3b2e', water: '#1f78b4', measure: '#d97706',
  misclosure: '#c026d3', error: '#dc2626', warning: '#d97706', success: '#15803d', surface: '#0f766e',
  breakline: '#b45309', parcel: '#4338ca', zone: '#be185d', 'cut-3': '#b2182b', 'cut-2': '#d6604d', 'cut-1': '#f4a582',
  neutral: '#e0e0e0', 'fill-1': '#92c5de', 'fill-2': '#4393c3', 'fill-3': '#2166ac',
};

export type MapPalette = Record<MapToken, string>;

/** Resolve every token from the document (call again when the theme changes). */
export function readPalette(el: Element | null = typeof document !== 'undefined' ? document.documentElement : null): MapPalette {
  const out = { ...FALLBACK };
  if (!el || typeof getComputedStyle === 'undefined') return out;
  const cs = getComputedStyle(el);
  for (const k of MAP_TOKENS) {
    const v = cs.getPropertyValue(`--oe-map-${k}`).trim();
    if (v) out[k] = v;
  }
  return out;
}

/** `var(--oe-map-x)` for DOM use (legend swatches, glyphs). */
export function planColour(token: MapToken): string {
  return `var(--oe-map-${token})`;
}

/** Symbol names that have an icon. */
export const SYMBOLS = ['control', 'benchmark', 'spot', 'tree', 'post', 'manhole', 'kerb', 'cross', 'diamond', 'square'] as const;
export type SymbolName = (typeof SYMBOLS)[number];

/**
 * Draw a symbol as an SDF-ready white shape, so `icon-color` tints it. 2x
 * pixel ratio for crisp edges. Returned as ImageData for `map.addImage`.
 */
export function symbolImage(name: SymbolName, size = 20): { width: number; height: number; data: Uint8Array } | null {
  if (typeof document === 'undefined') return null;
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const g = c.getContext('2d');
  if (!g) return null;
  g.strokeStyle = '#fff';
  g.fillStyle = '#fff';
  g.lineWidth = 2;
  const m = size / 2;
  const r = size / 2 - 3;
  g.beginPath();
  switch (name) {
    case 'control':
      g.moveTo(m, m - r);
      g.lineTo(m + r * 0.95, m + r * 0.75);
      g.lineTo(m - r * 0.95, m + r * 0.75);
      g.closePath();
      g.stroke();
      g.beginPath();
      g.arc(m, m + r * 0.15, 1.5, 0, Math.PI * 2);
      g.fill();
      break;
    case 'benchmark':
      g.arc(m, m, r, 0, Math.PI * 2);
      g.moveTo(m - r, m);
      g.lineTo(m + r, m);
      g.moveTo(m, m - r);
      g.lineTo(m, m + r);
      g.stroke();
      break;
    case 'tree':
      g.arc(m, m, r, 0, Math.PI * 2);
      g.stroke();
      g.beginPath();
      g.arc(m, m, 1.5, 0, Math.PI * 2);
      g.fill();
      break;
    case 'post':
      g.arc(m, m, r * 0.45, 0, Math.PI * 2);
      g.fill();
      break;
    case 'manhole':
      g.rect(m - r * 0.8, m - r * 0.8, r * 1.6, r * 1.6);
      g.moveTo(m - r * 0.8, m - r * 0.8);
      g.lineTo(m + r * 0.8, m + r * 0.8);
      g.moveTo(m + r * 0.8, m - r * 0.8);
      g.lineTo(m - r * 0.8, m + r * 0.8);
      g.stroke();
      break;
    case 'kerb':
      g.moveTo(m - r, m);
      g.lineTo(m + r, m);
      g.stroke();
      break;
    case 'cross':
      g.moveTo(m - r, m);
      g.lineTo(m + r, m);
      g.moveTo(m, m - r);
      g.lineTo(m, m + r);
      g.stroke();
      break;
    case 'diamond':
      g.moveTo(m, m - r);
      g.lineTo(m + r, m);
      g.lineTo(m, m + r);
      g.lineTo(m - r, m);
      g.closePath();
      g.fill();
      break;
    case 'square':
      g.rect(m - r * 0.75, m - r * 0.75, r * 1.5, r * 1.5);
      g.fill();
      break;
    case 'spot':
    default:
      g.arc(m, m, 2, 0, Math.PI * 2);
      g.fill();
  }
  const img = g.getImageData(0, 0, size, size);
  return { width: size, height: size, data: new Uint8Array(img.data.buffer) };
}

/** Symbol of a point: control kinds first, then the code library symbol. */
export function symbolFor(kind: string | undefined, librarySymbol: string | undefined): SymbolName {
  if (kind === 'control') return 'control';
  if (kind === 'benchmark') return 'benchmark';
  if (librarySymbol && (SYMBOLS as readonly string[]).includes(librarySymbol)) return librarySymbol as SymbolName;
  return 'spot';
}

/** Halo for every label: 1.5 px in the canvas background. */
function textPaint(p: MapPalette, colour: string): Record<string, unknown> {
  return { 'text-color': colour, 'text-halo-color': p.halo, 'text-halo-width': 1.5 };
}

/** Which label to show on points. */
export type LabelMode = 'id' | 'code' | 'z' | 'none';

function labelExpr(mode: LabelMode): unknown {
  if (mode === 'none') return '';
  if (mode === 'code') return ['coalesce', ['get', 'code'], ''];
  if (mode === 'z') return ['coalesce', ['get', 'z_text'], ''];
  return ['coalesce', ['get', 'label'], ''];
}

export interface StyleOptions {
  palette: MapPalette;
  labels: LabelMode;
  /** 0..1 opacity of the layer from the popover. */
  opacity: number;
}

/** Built-in style of a known layer id; unknown ids get a neutral line/point style. */
export function defaultStyle(layer: PlanLayerId, o: StyleOptions): PlanStyleLayer[] {
  const p = o.palette;
  const op = o.opacity;
  const geom = (t: string) => ['==', ['geometry-type'], t];
  switch (layer) {
    case 'control':
    case 'points':
      return [
        {
          id: 'sym',
          type: 'symbol',
          filter: geom('Point'),
          layout: {
            'icon-image': ['concat', 'oe-sym-', ['coalesce', ['get', 'symbol'], 'spot']],
            'icon-size': ['match', ['get', 'symbol'], ['control', 'benchmark'], 0.6, 0.5],
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
            'text-field': labelExpr(o.labels),
            'text-font': ['match', ['get', 'symbol'], ['control', 'benchmark'], ['literal', FONT_BOLD], ['literal', FONT_REGULAR]],
            'text-size': ['match', ['get', 'symbol'], ['control', 'benchmark'], 12, 11],
            'text-offset': [0.9, -0.2],
            'text-anchor': 'left',
            'text-optional': true,
            'text-allow-overlap': false,
            'symbol-sort-key': ['-', 0, ['coalesce', ['get', 'priority'], 40]],
          },
          paint: {
            'icon-color': ['match', ['get', 'symbol'], 'tree', p.tree, 'manhole', p.utility, 'post', p.fence, 'kerb', p.kerb, ['control', 'benchmark'], p.ink, p.topo],
            'icon-halo-color': p.halo,
            'icon-halo-width': 1,
            'icon-opacity': op,
            'text-opacity': op,
            ...textPaint(p, p.ink),
          },
        },
      ];
    case 'linework':
    case 'sketch':
      return [
        { id: 'fill', type: 'fill', filter: geom('Polygon'), paint: { 'fill-color': ['coalesce', ['get', 'colour_value'], p.line], 'fill-opacity': 0.08 * op } },
        {
          id: 'line',
          type: 'line',
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: { 'line-color': ['coalesce', ['get', 'colour_value'], p.line], 'line-width': layer === 'sketch' ? 1.5 : 1, 'line-opacity': op },
        },
        {
          id: 'pt',
          type: 'circle',
          filter: geom('Point'),
          paint: { 'circle-radius': 3, 'circle-color': p.ink, 'circle-stroke-color': p.halo, 'circle-stroke-width': 1, 'circle-opacity': op },
        },
        {
          id: 'text',
          type: 'symbol',
          filter: ['has', 'text'],
          layout: { 'text-field': ['get', 'text'], 'text-font': ['literal', FONT_REGULAR], 'text-size': 12, 'text-allow-overlap': false },
          paint: textPaint(p, p.ink),
        },
      ];
    case 'surfaces':
      return [{ id: 'line', type: 'line', paint: { 'line-color': p.surface, 'line-width': 1.5, 'line-opacity': op } }];
    case 'breaklines':
      return [{ id: 'line', type: 'line', paint: { 'line-color': p.breakline, 'line-width': 1.5, 'line-dasharray': [2, 1], 'line-opacity': op } }];
    case 'heat':
      return [
        {
          id: 'fill',
          type: 'fill',
          paint: {
            // RdBu, neutral inside the dead band.
            'fill-color': [
              'step', ['*', ['coalesce', ['get', 'dh'], 0], ['match', ['get', 'side'], 'cut', -1, 1]],
              p['cut-3'], -1, p['cut-2'], -0.5, p['cut-1'], -0.05, p.neutral, 0.05, p['fill-1'], 0.5, p['fill-2'], 1, p['fill-3'],
            ],
            'fill-opacity': 0.75 * op,
          },
        },
      ];
    case 'measure':
      return [
        { id: 'fill', type: 'fill', filter: geom('Polygon'), paint: { 'fill-color': p.measure, 'fill-opacity': 0.12 } },
        { id: 'line', type: 'line', paint: { 'line-color': p.measure, 'line-width': 2, 'line-dasharray': [3, 1.5] } },
        { id: 'pt', type: 'circle', filter: geom('Point'), paint: { 'circle-radius': 3.5, 'circle-color': p.measure, 'circle-stroke-color': p.halo, 'circle-stroke-width': 1.5 } },
        {
          id: 'text',
          type: 'symbol',
          filter: ['has', 'text'],
          layout: {
            'text-field': ['get', 'text'],
            'text-font': ['literal', FONT_BOLD],
            'text-size': 12,
            'symbol-placement': ['match', ['geometry-type'], 'LineString', 'line-center', 'point'],
            'text-keep-upright': true,
            'text-offset': [0, -0.8],
            'text-allow-overlap': true,
          },
          paint: textPaint(p, p.ink),
        },
      ];
    default:
      return [
        { id: 'fill', type: 'fill', filter: geom('Polygon'), paint: { 'fill-color': p.accent, 'fill-opacity': 0.08 * op } },
        { id: 'line', type: 'line', paint: { 'line-color': p['ink-2'], 'line-width': 1, 'line-opacity': op } },
        { id: 'pt', type: 'circle', filter: geom('Point'), paint: { 'circle-radius': 3, 'circle-color': p['ink-2'], 'circle-opacity': op } },
      ];
  }
}

/** Overlay styles drawn above every layer: hover, selection, vertex handles, findings. */
export function overlayStyle(p: MapPalette): PlanStyleLayer[] {
  const role = (r: string) => ['==', ['get', 'role'], r];
  return [
    { id: 'hover-line', type: 'line', filter: ['all', role('hover'), ['!=', ['geometry-type'], 'Point']], paint: { 'line-color': p.accent, 'line-width': 4, 'line-opacity': 0.6 } },
    { id: 'hover-pt', type: 'circle', filter: ['all', role('hover'), ['==', ['geometry-type'], 'Point']], paint: { 'circle-radius': 8, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': p.accent, 'circle-stroke-width': 2, 'circle-stroke-opacity': 0.6 } },
    { id: 'sel-fill', type: 'fill', filter: ['all', role('selected'), ['==', ['geometry-type'], 'Polygon']], paint: { 'fill-color': p.accent, 'fill-opacity': 0.1 } },
    { id: 'sel-line', type: 'line', filter: ['all', role('selected'), ['!=', ['geometry-type'], 'Point']], paint: { 'line-color': p.accent, 'line-width': 2.5 } },
    { id: 'sel-pt', type: 'circle', filter: ['all', role('selected'), ['==', ['geometry-type'], 'Point']], paint: { 'circle-radius': 7, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': p.accent, 'circle-stroke-width': 2.5 } },
    { id: 'mid-handle', type: 'circle', filter: role('mid'), paint: { 'circle-radius': 3.5, 'circle-color': p.halo, 'circle-stroke-color': p.accent, 'circle-stroke-width': 1, 'circle-opacity': 0.9 } },
    { id: 'handle', type: 'circle', filter: role('handle'), paint: { 'circle-radius': 4, 'circle-color': p.halo, 'circle-stroke-color': p.accent, 'circle-stroke-width': 2 } },
    { id: 'handle-on', type: 'circle', filter: role('handle-on'), paint: { 'circle-radius': 5, 'circle-color': p.accent, 'circle-stroke-color': p.halo, 'circle-stroke-width': 2 } },
    { id: 'finding', type: 'symbol', filter: role('finding'), layout: { 'icon-image': 'oe-sym-cross', 'icon-rotate': 45, 'icon-size': 0.7, 'icon-allow-overlap': true }, paint: { 'icon-color': p.error } },
    { id: 'box', type: 'fill', filter: role('box'), paint: { 'fill-color': p.accent, 'fill-opacity': 0.06 } },
    { id: 'box-line', type: 'line', filter: ['all', role('box'), ['!=', ['get', 'crossing'], 1]], paint: { 'line-color': p.accent, 'line-width': 1 } },
    { id: 'box-cross', type: 'line', filter: ['all', role('box'), ['==', ['get', 'crossing'], 1]], paint: { 'line-color': p.accent, 'line-width': 1, 'line-dasharray': [3, 2] } },
  ];
}

/** Grid lines for the paper style: a minor step and every 5th line major. */
export function gridStep(metresPerPixel: number): number {
  const target = metresPerPixel * 60;
  const pow = 10 ** Math.floor(Math.log10(target));
  return [1, 2, 5, 10].map((k) => k * pow).find((s) => s >= target) ?? pow * 10;
}
