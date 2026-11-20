// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Plane geometry on the project grid ([E, N] metres). Pure functions, no map. */

import type { GridXY, GridXYZ, PlanFeature } from '../types';

export type Segment = [GridXY, GridXY];

export const xy = (p: GridXYZ): GridXY => [p[0], p[1]];

export function dist(a: GridXY, b: GridXY): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

export function midpoint(a: GridXY, b: GridXY): GridXY {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
}

/** Closest point on segment ab to p, and its parameter t in [0, 1]. */
export function nearestOnSegment(p: GridXY, a: GridXY, b: GridXY): { point: GridXY; t: number } {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return { point: a, t: 0 };
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  return { point: [a[0] + t * dx, a[1] + t * dy], t };
}

/** Foot of the perpendicular from p onto the infinite line through ab, with its parameter. */
export function perpendicularFoot(p: GridXY, a: GridXY, b: GridXY): { point: GridXY; t: number } | null {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return null;
  const t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2;
  return { point: [a[0] + t * dx, a[1] + t * dy], t };
}

/** Proper or touching intersection of two segments; null when parallel or apart. */
export function segmentIntersection(a: GridXY, b: GridXY, c: GridXY, d: GridXY): GridXY | null {
  const r: GridXY = [b[0] - a[0], b[1] - a[1]];
  const s: GridXY = [d[0] - c[0], d[1] - c[1]];
  const den = r[0] * s[1] - r[1] * s[0];
  if (Math.abs(den) < 1e-12) return null;
  const qp: GridXY = [c[0] - a[0], c[1] - a[1]];
  const t = (qp[0] * s[1] - qp[1] * s[0]) / den;
  const u = (qp[0] * r[1] - qp[1] * r[0]) / den;
  const eps = 1e-9;
  if (t < -eps || t > 1 + eps || u < -eps || u > 1 + eps) return null;
  return [a[0] + t * r[0], a[1] + t * r[1]];
}

/** Signed shoelace area (positive counter-clockwise). The ring is implicitly closed. */
export function signedArea(ring: readonly GridXYZ[]): number {
  let s = 0;
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i]!;
    const q = ring[(i + 1) % ring.length]!;
    s += p[0] * q[1] - q[0] * p[1];
  }
  return s / 2;
}

export function ringArea(ring: readonly GridXYZ[]): number {
  return Math.abs(signedArea(ring));
}

export function pathLength(path: readonly GridXYZ[], closed = false): number {
  let s = 0;
  for (let i = 1; i < path.length; i++) s += dist(xy(path[i - 1]!), xy(path[i]!));
  if (closed && path.length > 2) s += dist(xy(path[path.length - 1]!), xy(path[0]!));
  return s;
}

/** Angle at `vertex` from `from` to `to`, clockwise, degrees in [0, 360). */
export function angleAt(from: GridXY, vertex: GridXY, to: GridXY): number {
  const a1 = Math.atan2(from[0] - vertex[0], from[1] - vertex[1]);
  const a2 = Math.atan2(to[0] - vertex[0], to[1] - vertex[1]);
  let d = ((a2 - a1) * 180) / Math.PI;
  d %= 360;
  return d < 0 ? d + 360 : d;
}

/** A point at `distance` along grid azimuth `azimuth` (degrees from grid north) from `from`. */
export function polarPoint(from: GridXY, azimuth: number, distance: number): GridXY {
  const r = (azimuth * Math.PI) / 180;
  return [from[0] + distance * Math.sin(r), from[1] + distance * Math.cos(r)];
}

/** Circle through three points, or null when they are collinear. */
export function circleThrough(a: GridXY, b: GridXY, c: GridXY): { centre: GridXY; radius: number } | null {
  const d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]));
  if (Math.abs(d) < 1e-9) return null;
  const a2 = a[0] ** 2 + a[1] ** 2;
  const b2 = b[0] ** 2 + b[1] ** 2;
  const c2 = c[0] ** 2 + c[1] ** 2;
  const ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d;
  const uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d;
  return { centre: [ux, uy], radius: dist([ux, uy], a) };
}

/**
 * Arc from `a` through `b` to `c`, densified so that the chord deviates from
 * the arc by at most `sagitta` metres. Collinear points give the straight line.
 */
export function arcThrough(a: GridXY, b: GridXY, c: GridXY, sagitta = 0.005): GridXY[] {
  const circle = circleThrough(a, b, c);
  if (!circle) return [a, c];
  const { centre, radius } = circle;
  const ang = (p: GridXY) => Math.atan2(p[1] - centre[1], p[0] - centre[0]);
  const a0 = ang(a);
  let am = ang(b) - a0;
  let a1 = ang(c) - a0;
  const wrap = (x: number) => ((x % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  am = wrap(am);
  a1 = wrap(a1);
  // Counter-clockwise when b lies between a and c going CCW, else clockwise.
  const sweep = am < a1 ? a1 : a1 - 2 * Math.PI;
  const step = 2 * Math.acos(Math.max(-1, Math.min(1, 1 - sagitta / radius)));
  const n = Math.max(2, Math.min(720, Math.ceil(Math.abs(sweep) / Math.max(step, 1e-6))));
  const out: GridXY[] = [];
  for (let i = 0; i <= n; i++) {
    const t = a0 + (sweep * i) / n;
    out.push([centre[0] + radius * Math.cos(t), centre[1] + radius * Math.sin(t)]);
  }
  out[0] = a;
  out[n] = c;
  return out;
}

/** Parallel polyline at `offset` metres (positive = right of the direction of travel), mitred joins. */
export function offsetPath(path: readonly GridXY[], offset: number): GridXY[] {
  if (path.length < 2) return [...path];
  const normals: GridXY[] = [];
  for (let i = 1; i < path.length; i++) {
    const [a, b] = [path[i - 1]!, path[i]!];
    const len = dist(a, b) || 1;
    normals.push([(b[1] - a[1]) / len, -(b[0] - a[0]) / len]);
  }
  const out: GridXY[] = [];
  for (let i = 0; i < path.length; i++) {
    const p = path[i]!;
    if (i === 0 || i === path.length - 1) {
      const nrm = normals[i === 0 ? 0 : normals.length - 1]!;
      out.push([p[0] + nrm[0] * offset, p[1] + nrm[1] * offset]);
      continue;
    }
    const n1 = normals[i - 1]!;
    const n2 = normals[i]!;
    const bx = n1[0] + n2[0];
    const by = n1[1] + n2[1];
    const blen = Math.hypot(bx, by);
    if (blen < 1e-9) {
      out.push([p[0] + n1[0] * offset, p[1] + n1[1] * offset]);
      continue;
    }
    const cos = (n1[0] * bx + n1[1] * by) / blen;
    const k = offset / Math.max(cos, 0.1);
    out.push([p[0] + (bx / blen) * k, p[1] + (by / blen) * k]);
  }
  return out;
}

export function pointInRing(p: GridXY, ring: readonly GridXYZ[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Crossing points of a ring with itself (non-adjacent edges). */
export function ringSelfIntersections(ring: readonly GridXYZ[]): GridXY[] {
  const n = ring.length;
  const out: GridXY[] = [];
  if (n < 4) return out;
  for (let i = 0; i < n; i++) {
    const a = xy(ring[i]!);
    const b = xy(ring[(i + 1) % n]!);
    for (let j = i + 2; j < n; j++) {
      if (i === 0 && j === n - 1) continue;
      const hit = segmentIntersection(a, b, xy(ring[j]!), xy(ring[(j + 1) % n]!));
      if (hit) out.push(hit);
    }
  }
  return out;
}

export type BBox = [number, number, number, number];

export function bboxOf(points: Iterable<GridXYZ>): BBox | null {
  let b: BBox | null = null;
  for (const p of points) {
    if (!b) b = [p[0], p[1], p[0], p[1]];
    else b = [Math.min(b[0], p[0]), Math.min(b[1], p[1]), Math.max(b[2], p[0]), Math.max(b[3], p[1])];
  }
  return b;
}

/** Every vertex of a feature, in order (rings without the closing repeat). */
export function featureVertices(f: PlanFeature): GridXY[] {
  const g = f.geometry;
  if (g.type === 'Point') return [xy(g.coordinates)];
  if (g.type === 'LineString') return g.coordinates.map(xy);
  return g.coordinates.flatMap((r) => r.map(xy));
}

/** Every segment of a feature (rings closed). */
export function featureSegments(f: PlanFeature): Segment[] {
  const g = f.geometry;
  const out: Segment[] = [];
  const add = (path: readonly GridXYZ[], closed: boolean) => {
    for (let i = 1; i < path.length; i++) out.push([xy(path[i - 1]!), xy(path[i]!)]);
    if (closed && path.length > 2) out.push([xy(path[path.length - 1]!), xy(path[0]!)]);
  };
  if (g.type === 'LineString') add(g.coordinates, false);
  else if (g.type === 'Polygon') g.coordinates.forEach((r) => add(r, true));
  return out;
}

export function featuresBBox(features: Iterable<PlanFeature>): BBox | null {
  const pts: GridXY[] = [];
  for (const f of features) pts.push(...featureVertices(f));
  return bboxOf(pts);
}

/** Distance from p to a feature (0 inside a polygon). */
export function distanceToFeature(p: GridXY, f: PlanFeature): number {
  const g = f.geometry;
  if (g.type === 'Point') return dist(p, xy(g.coordinates));
  if (g.type === 'Polygon' && g.coordinates[0] && pointInRing(p, g.coordinates[0])) return 0;
  let best = Infinity;
  for (const [a, b] of featureSegments(f)) best = Math.min(best, dist(p, nearestOnSegment(p, a, b).point));
  return best;
}
