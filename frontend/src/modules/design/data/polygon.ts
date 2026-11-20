// Design module (ERP side of the design editor link).
/**
 * Plot outline helpers. The brief stores the plot as an RFC 7946 Polygon: WGS84 [lon, lat],
 * first ring closed and counter-clockwise. The editor works with the open list of vertices.
 */

export type LngLat = [number, number];

export interface GeoPolygon {
  type: 'Polygon';
  coordinates: number[][][];
}

/** Mean Earth radius (IUGG), metres. */
export const EARTH_RADIUS_M = 6371008.8;
/** 7 decimals of a degree is about 1 cm: finer digits are noise from the pointer. */
const DECIMALS = 7;

const rad = (deg: number) => (deg * Math.PI) / 180;

function round(v: number): number {
  const f = 10 ** DECIMALS;
  return Math.round(v * f) / f;
}

function same(a: LngLat, b: LngLat): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

/** Vertices without the closing point and without consecutive duplicates. */
export function openRing(points: LngLat[]): LngLat[] {
  const out: LngLat[] = [];
  for (const p of points) {
    if (!out.length || !same(out[out.length - 1]!, p)) out.push([p[0], p[1]]);
  }
  while (out.length > 1 && same(out[0]!, out[out.length - 1]!)) out.pop();
  return out;
}

/** Closed ring: the first vertex repeated at the end. */
export function closeRing(points: LngLat[]): LngLat[] {
  const open = openRing(points);
  return open.length ? [...open, [open[0]![0], open[0]![1]]] : [];
}

/** Longitude into [-180, 180]; a click on a repeated world copy gives values beyond. */
export function wrapLon(lon: number): number {
  if (lon >= -180 && lon <= 180) return lon;
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}

/**
 * Longitudes made continuous along the ring (each step at most 180 degrees), so an outline that
 * crosses the antimeridian (179.999 then -179.999) stays one small shape in a planar frame.
 */
function unwrapped(ring: LngLat[]): LngLat[] {
  const out: LngLat[] = [];
  let prev = 0;
  ring.forEach(([lon, lat], i) => {
    let l = lon;
    if (i > 0) l = prev + (((lon - prev + 540) % 360) - 180);
    out.push([l, lat]);
    prev = l;
  });
  return out;
}

/**
 * Twice the signed planar area in a local equirectangular frame (degrees scaled by cos of the mean
 * latitude). Positive means counter-clockwise; only the sign is used.
 */
export function signedArea2(points: LngLat[]): number {
  const ring = unwrapped(openRing(points));
  if (ring.length < 3) return 0;
  const k = Math.cos(rad(ring.reduce((s, p) => s + p[1], 0) / ring.length));
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!;
    const b = ring[(i + 1) % ring.length]!;
    sum += a[0] * k * b[1] - b[0] * k * a[1];
  }
  return sum;
}

export function isCounterClockwise(points: LngLat[]): boolean {
  return signedArea2(points) > 0;
}

/** Same vertices, counter-clockwise, open. */
export function toCounterClockwise(points: LngLat[]): LngLat[] {
  const ring = openRing(points);
  return signedArea2(ring) < 0 ? [ring[0]!, ...ring.slice(1).reverse()] : ring;
}

/**
 * Area on the sphere in m2, edges straight in longitude/latitude as RFC 7946 defines them
 * (spherical excess by the trapezoid rule over longitude). Longitudes are unwrapped first, so an
 * outline across the antimeridian (179.999 then -179.999) is the small shape it is.
 */
export function areaM2(points: LngLat[]): number {
  const ring = unwrapped(openRing(points));
  if (ring.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const prev = ring[(i + ring.length - 1) % ring.length]!;
    const cur = ring[i]!;
    const next = ring[(i + 1) % ring.length]!;
    sum += (rad(next[0]) - rad(prev[0])) * Math.sin(rad(cur[1]));
  }
  return Math.abs((sum * EARTH_RADIUS_M * EARTH_RADIUS_M) / 2);
}

/** Great-circle distance in metres. */
export function distanceM(a: LngLat, b: LngLat): number {
  const dLat = rad(b[1] - a[1]);
  const dLon = rad(b[0] - a[0]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Length of the closed outline in metres. */
export function perimeterM(points: LngLat[]): number {
  const ring = closeRing(points);
  let sum = 0;
  for (let i = 1; i < ring.length; i++) sum += distanceM(ring[i - 1]!, ring[i]!);
  return sum;
}

function orient(a: LngLat, b: LngLat, c: LngLat): number {
  const v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  return v > 0 ? 1 : v < 0 ? -1 : 0;
}

function onSegment(a: LngLat, b: LngLat, p: LngLat): boolean {
  return (
    Math.min(a[0], b[0]) <= p[0] && p[0] <= Math.max(a[0], b[0]) &&
    Math.min(a[1], b[1]) <= p[1] && p[1] <= Math.max(a[1], b[1])
  );
}

function segmentsCross(a: LngLat, b: LngLat, c: LngLat, d: LngLat): boolean {
  const o1 = orient(a, b, c);
  const o2 = orient(a, b, d);
  const o3 = orient(c, d, a);
  const o4 = orient(c, d, b);
  if (o1 !== o2 && o3 !== o4) return true;
  return (
    (o1 === 0 && onSegment(a, b, c)) || (o2 === 0 && onSegment(a, b, d)) ||
    (o3 === 0 && onSegment(c, d, a)) || (o4 === 0 && onSegment(c, d, b))
  );
}

/** True when two non-adjacent edges of the outline touch or cross. */
export function selfIntersects(points: LngLat[]): boolean {
  const ring = unwrapped(openRing(points));
  const n = ring.length;
  if (n < 4) return false;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (j === i + 1 || (i === 0 && j === n - 1)) continue; // neighbours share a vertex
      if (segmentsCross(ring[i]!, ring[(i + 1) % n]!, ring[j]!, ring[(j + 1) % n]!)) return true;
    }
  }
  return false;
}

export type PlotProblem = 'too_few_points' | 'degenerate' | 'self_intersecting' | 'out_of_range' | 'too_large';

/**
 * Largest outline accepted: 100 km2 (10 000 ha). A building site is far smaller; anything above
 * is almost always a swapped or mistyped coordinate (degrees instead of a fraction of a degree),
 * and the great-circle outline model stops being a fair stand-in for a plot.
 */
export const MAX_PLOT_AREA_M2 = 100e6;

function collinear(points: LngLat[]): boolean {
  const ring = unwrapped(points);
  const o = ring[0]!;
  const far = ring.reduce((best, p) => (Math.hypot(p[0] - o[0], p[1] - o[1]) > Math.hypot(best[0] - o[0], best[1] - o[1]) ? p : best), o);
  const d = Math.hypot(far[0] - o[0], far[1] - o[1]);
  if (d === 0) return true;
  return ring.every((p) => Math.abs((far[0] - o[0]) * (p[1] - o[1]) - (far[1] - o[1]) * (p[0] - o[0])) <= 1e-9 * d * d);
}

/** Why an outline cannot be stored, or null when it can. */
export function plotProblem(points: LngLat[]): PlotProblem | null {
  const ring = openRing(points);
  if (ring.some(([lon, lat]) => !(lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90))) return 'out_of_range';
  if (ring.length < 3) return 'too_few_points';
  if (collinear(ring)) return 'degenerate';
  if (selfIntersects(ring)) return 'self_intersecting';
  const area = areaM2(ring);
  if (area === 0) return 'degenerate';
  if (area > MAX_PLOT_AREA_M2) return 'too_large';
  return null;
}

/**
 * GeoJSON Polygon for the brief: outline rounded, closed, counter-clockwise. Inner rings of
 * `previous` (holes from an imported plot) are kept as they were.
 */
export function toPolygon(points: LngLat[], previous?: GeoPolygon | null): GeoPolygon {
  const rounded = points.map(([lon, lat]) => [round(lon), round(lat)] as LngLat);
  const holes = previous?.coordinates?.slice(1) ?? [];
  return { type: 'Polygon', coordinates: [closeRing(toCounterClockwise(rounded)), ...holes] };
}

/** Editable vertices of the outline ring. */
export function fromPolygon(polygon: GeoPolygon | null | undefined): LngLat[] {
  const ring = polygon?.coordinates?.[0];
  if (!ring) return [];
  return openRing(ring.map((p) => [p[0]!, p[1]!] as LngLat));
}

/** [west, south, east, north] or null for an empty outline. */
export function bounds(points: LngLat[]): [number, number, number, number] | null {
  if (!points.length) return null;
  const lons = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}
