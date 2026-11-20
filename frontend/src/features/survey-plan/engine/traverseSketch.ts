// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The traverse sketch of a reduced field book: grey dashed legs as observed
 * (angles corrected, before the linear adjustment), the adjusted legs over
 * them, the stations, and the misclosure vector from where the run ended to
 * where it should have. A closing error of a few millimetres on a 600 m loop
 * cannot be seen, so the vector is drawn a round power of ten times longer
 * and the factor is printed next to it.
 */

import type { GridXY, PlanFeature } from '../types';

export interface SketchStation {
  station_id: string;
  e: number;
  n: number;
}

export interface SketchInput {
  shape: string;
  unadjusted: SketchStation[];
  adjusted: SketchStation[];
  computedEnd: SketchStation;
  fixedEnd: SketchStation;
  /** Known points (start, backsight, closing) drawn as control triangles. */
  control?: SketchStation[];
}

const xy = (s: SketchStation): GridXY => [s.e, s.n];

/** Extent (larger side of the bounding box) of a set of stations, metres. */
export function extentOf(pts: readonly SketchStation[]): number {
  if (!pts.length) return 0;
  const es = pts.map((p) => p.e);
  const ns = pts.map((p) => p.n);
  return Math.max(Math.max(...es) - Math.min(...es), Math.max(...ns) - Math.min(...ns));
}

/**
 * A power of ten that draws a misclosure of `f` metres at about 6 % of the
 * traverse extent, never below 1 (a gross error is drawn true to scale).
 */
export function misclosureScale(f: number, extent: number): number {
  if (!(f > 0) || !(extent > 0)) return 1;
  const raw = (0.06 * extent) / f;
  if (raw <= 1) return 1;
  return 10 ** Math.round(Math.log10(raw));
}

/** Legs of a run: closed back to the first station for a loop. */
function legs(pts: readonly SketchStation[], closeTo: SketchStation | null): [GridXY, GridXY][] {
  const out: [GridXY, GridXY][] = [];
  for (let i = 0; i < pts.length - 1; i++) out.push([xy(pts[i]!), xy(pts[i + 1]!)]);
  if (closeTo && pts.length) out.push([xy(pts[pts.length - 1]!), xy(closeTo)]);
  return out;
}

export interface Sketch {
  features: PlanFeature[];
  scale: number;
  misclosure: number;
}

export function traverseSketch(input: SketchInput): Sketch {
  const loop = input.shape === 'loop';
  const f = Math.hypot(input.fixedEnd.e - input.computedEnd.e, input.fixedEnd.n - input.computedEnd.n);
  const scale = misclosureScale(f, extentOf(input.adjusted.length ? input.adjusted : input.unadjusted));
  const features: PlanFeature[] = [];
  // The observed run ends at the computed end, not back on the start.
  legs(input.unadjusted, input.computedEnd).forEach(([a, b], i) =>
    features.push({ id: `trav-raw:${i}`, layer: 'traverse', geometry: { type: 'LineString', coordinates: [a, b] }, properties: { role: 'raw', label: '' } }),
  );
  legs(input.adjusted, loop ? input.adjusted[0] ?? null : input.fixedEnd).forEach(([a, b], i) =>
    features.push({ id: `trav-adj:${i}`, layer: 'traverse', geometry: { type: 'LineString', coordinates: [a, b] }, properties: { role: 'adjusted', label: '' } }),
  );
  input.adjusted.forEach((s, i) =>
    features.push({ id: `trav-stn:${i}`, layer: 'traverse', geometry: { type: 'Point', coordinates: xy(s) }, properties: { role: 'station', label: s.station_id } }),
  );
  (input.control ?? []).forEach((s, i) =>
    features.push({ id: `trav-ctl:${i}`, layer: 'control', geometry: { type: 'Point', coordinates: xy(s) }, properties: { role: 'control', label: s.station_id, kind: 'control' } }),
  );
  if (f > 0) {
    const a = xy(input.computedEnd);
    const b: GridXY = [a[0] + (input.fixedEnd.e - a[0]) * scale, a[1] + (input.fixedEnd.n - a[1]) * scale];
    features.push({ id: 'trav-misclosure', layer: 'traverse', geometry: { type: 'LineString', coordinates: [a, b] }, properties: { role: 'misclosure', label: `x${scale}`, scale } });
  }
  return { features, scale, misclosure: f };
}
