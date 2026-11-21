// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Station error ellipses of a least-squares adjustment as plan rings. The
 * semi-axes are millimetres on a network hundreds of metres across, so they
 * are drawn exaggerated by a round factor the plan prints ("ellipses x N").
 */

import type { GridXY, PlanFeature } from '../types';

export interface StationEllipse {
  ref: string;
  /** Semi-major and semi-minor axis, metres. */
  a_m: number;
  b_m: number;
  /** Azimuth of the major axis, degrees clockwise from grid north. */
  azimuth_deg: number;
}

/** Round exaggeration (1, 2, 5 x 10^k) that draws the largest ellipse near `share` of the network span. */
export function ellipseScale(ellipses: readonly StationEllipse[], spanM: number, share = 0.06): number {
  const biggest = Math.max(0, ...ellipses.map((e) => e.a_m));
  if (!(biggest > 0) || !(spanM > 0)) return 1;
  const raw = (spanM * share) / biggest;
  if (raw <= 1) return 1;
  const p = 10 ** Math.floor(Math.log10(raw));
  const k = raw / p;
  return (k >= 5 ? 5 : k >= 2 ? 2 : 1) * p;
}

/** Ring of an ellipse centred at `at`, axes scaled by `scale`; the last vertex is not repeated. */
export function ellipseRing(at: GridXY, e: StationEllipse, scale: number, segments = 48): GridXY[] {
  const t = (e.azimuth_deg * Math.PI) / 180;
  // Major axis unit vector in (E, N) for an azimuth from north, minor axis perpendicular.
  const [ue, un] = [Math.sin(t), Math.cos(t)];
  const [ve, vn] = [Math.cos(t), -Math.sin(t)];
  const a = e.a_m * scale;
  const b = e.b_m * scale;
  const out: GridXY[] = [];
  for (let i = 0; i < segments; i++) {
    const w = (2 * Math.PI * i) / segments;
    const ca = a * Math.cos(w);
    const sb = b * Math.sin(w);
    out.push([at[0] + ca * ue + sb * ve, at[1] + ca * un + sb * vn]);
  }
  return out;
}

/** Ellipse rings and major-axis ticks for the stations found in `positions`. */
export function ellipseFeatures(ellipses: readonly StationEllipse[], positions: ReadonlyMap<string, GridXY>, scale: number): PlanFeature[] {
  const out: PlanFeature[] = [];
  for (const e of ellipses) {
    const at = positions.get(e.ref);
    if (!at || !(e.a_m > 0)) continue;
    out.push({
      id: `ellipse:${e.ref}`,
      layer: 'ellipses',
      geometry: { type: 'Polygon', coordinates: [ellipseRing(at, e, scale)] },
      properties: { role: 'ellipse', station: e.ref, a_m: e.a_m, b_m: e.b_m, azimuth_deg: e.azimuth_deg },
    });
    const t = (e.azimuth_deg * Math.PI) / 180;
    const d = e.a_m * scale;
    out.push({
      id: `ellipse-axis:${e.ref}`,
      layer: 'ellipses',
      geometry: { type: 'LineString', coordinates: [[at[0] - d * Math.sin(t), at[1] - d * Math.cos(t)], [at[0] + d * Math.sin(t), at[1] + d * Math.cos(t)]] },
      properties: { role: 'ellipse-axis', station: e.ref },
    });
  }
  return out;
}
