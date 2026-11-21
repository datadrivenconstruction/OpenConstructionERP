// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Grid features to the GeoJSON MapLibre draws. Pure functions: every
 * coordinate goes through the view transform here and nowhere else.
 */

import type { Feature, FeatureCollection, Geometry } from 'geojson';
import { symbolFor, type MapPalette, type MapToken } from './cartography';
import { parseCode, type CodeEntry } from './engine/linework';
import type { BBox } from './engine/geometry';
import type { ViewTransform } from './engine/viewTransform';
import type { GridXY, GridXYZ, PlanFeature, PlanGeometry } from './types';
import { fmtFixed } from '@/shared/lib/formatters';

type ToView = ViewTransform['toView'];

export function toViewGeometry(g: PlanGeometry, toView: ToView): Geometry {
  const pt = (c: GridXYZ) => toView([c[0], c[1]]);
  switch (g.type) {
    case 'Point':
      return { type: 'Point', coordinates: pt(g.coordinates) };
    case 'LineString':
      return { type: 'LineString', coordinates: g.coordinates.map(pt) };
    case 'Polygon':
      return { type: 'Polygon', coordinates: g.coordinates.map((r) => r.map(pt)) };
  }
}

export const EMPTY_FC: FeatureCollection = { type: 'FeatureCollection', features: [] };

export interface DecorateOptions {
  palette: MapPalette;
  library: readonly CodeEntry[];
  /** Label priority of the layer (control 100 ... topo 40). */
  priority: number;
  /** Decimal places of the height label. */
  zDecimals: number;
}

/** Display properties MapLibre styles read: symbol, colour value, label, code, height text. */
export function decorate(f: PlanFeature, o: DecorateOptions): Record<string, unknown> {
  const p = f.properties;
  const out: Record<string, unknown> = { ...p, fid: f.id };
  const code = typeof p.code === 'string' ? p.code : '';
  if (f.geometry.type === 'Point') {
    const entry = code ? parseCode(code, o.library).entry : null;
    out.symbol = symbolFor(typeof p.kind === 'string' ? p.kind : f.layer === 'control' ? 'control' : undefined, entry?.symbol ?? (typeof p.symbol === 'string' ? p.symbol : undefined));
    const z = f.geometry.coordinates[2];
    if (z != null) out.z_text = fmtFixed(z, o.zDecimals);
    out.priority = (p.kind === 'control' || f.layer === 'control' ? 100 : o.priority) as number;
  }
  const colour = paletteValue(p.colour, o.palette);
  if (colour) out.colour_value = colour;
  const fill = paletteValue(p.fill, o.palette);
  if (fill) out.fill_value = fill;
  const label = paletteValue(p.label_colour, o.palette);
  if (label) out.label_value = label;
  return out;
}

/** A map token (`parcel`) or its CSS variable (`var(--oe-map-parcel)`) as the resolved colour. */
export function paletteValue(v: unknown, palette: MapPalette): string | null {
  if (typeof v !== 'string' || !v) return null;
  const m = /^var\(--oe-map-([a-z0-9-]+)\)$/.exec(v.trim());
  const token = (m ? m[1] : v) as MapToken;
  return token in palette ? palette[token] : null;
}

export function toCollection(features: readonly PlanFeature[], toView: ToView, o: DecorateOptions): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: features.map((f): Feature => ({ type: 'Feature', id: undefined, geometry: toViewGeometry(f.geometry, toView), properties: decorate(f, o) })),
  };
}

/** Grid lines over the visible extent: `step` metres, every 5th line major. Capped at 400 lines. */
export function gridLines(bbox: BBox, step: number, toView: ToView): FeatureCollection {
  const [e0, n0, e1, n1] = bbox;
  const out: Feature[] = [];
  if (!(step > 0) || (e1 - e0) / step > 200 || (n1 - n0) / step > 200) return EMPTY_FC;
  const line = (a: GridXY, b: GridXY, major: boolean): Feature => {
    // Densify so a projected grid line stays straight on the grid, not on the map.
    const pts: [number, number][] = [];
    for (let i = 0; i <= 8; i++) pts.push(toView([a[0] + ((b[0] - a[0]) * i) / 8, a[1] + ((b[1] - a[1]) * i) / 8]));
    return { type: 'Feature', geometry: { type: 'LineString', coordinates: pts }, properties: { major: major ? 1 : 0 } };
  };
  for (let e = Math.ceil(e0 / step) * step; e <= e1; e += step) out.push(line([e, n0], [e, n1], Math.round(e / step) % 5 === 0));
  for (let n = Math.ceil(n0 / step) * step; n <= n1; n += step) out.push(line([e0, n], [e1, n], Math.round(n / step) % 5 === 0));
  return { type: 'FeatureCollection', features: out };
}

/** Overlay features (hover, selection, handles, findings, box) with their `role`. */
export function overlayFeature(role: string, g: PlanGeometry, toView: ToView, extra: Record<string, unknown> = {}): Feature {
  return { type: 'Feature', geometry: toViewGeometry(g, toView), properties: { role, ...extra } };
}

/** Grid bbox of a view extent given as its four corners in lon/lat. */
export function gridBBoxOfView(corners: readonly [number, number][], toGrid: ViewTransform['toGrid']): BBox {
  const g = corners.map((c) => toGrid(c));
  const es = g.map((p) => p[0]);
  const ns = g.map((p) => p[1]);
  return [Math.min(...es), Math.min(...ns), Math.max(...es), Math.max(...ns)];
}
