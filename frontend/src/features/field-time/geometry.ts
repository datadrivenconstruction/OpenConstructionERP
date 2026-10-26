// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure geometry for the geofenced time clock​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: what the map draws and the
 * editor's "would this point be inside" preview. The server decides the real
 * inside/outside verdict; nothing here is authoritative.
 */

/** [lat, lng], the order the API uses. */
export type LatLng = [number, number];

const EARTH_RADIUS_M = 6371008.8;
const toRad = (d: number) => (d * Math.PI) / 180;

/** Great-circle distance in metres. */
export function haversineM(a: LatLng, b: LatLng): number {
  const dLat = toRad(b[0] - a[0]);
  const dLng = toRad(b[1] - a[1]);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** A closed GeoJSON ring ([lng, lat] pairs) approximating a circle. */
export function circlePolygon(centre: LatLng, radiusM: number, steps = 48): [number, number][] {
  const [lat, lng] = centre;
  const dLat = radiusM / EARTH_RADIUS_M;
  const cosLat = Math.max(1e-6, Math.cos(toRad(lat)));
  const ring: [number, number][] = [];
  for (let i = 0; i < steps; i += 1) {
    const ang = (2 * Math.PI * i) / steps;
    ring.push([
      lng + ((dLat * Math.sin(ang)) / cosLat) * (180 / Math.PI),
      lat + dLat * Math.cos(ang) * (180 / Math.PI),
    ]);
  }
  ring.push(ring[0]!);
  return ring;
}

/** Ray-casting point-in-polygon on [lat, lng] vertices (ring need not be closed). */
export function pointInPolygon(point: LatLng, polygon: LatLng[]): boolean {
  if (polygon.length < 3) return false;
  const [py, px] = point;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const [yi, xi] = polygon[i]!;
    const [yj, xj] = polygon[j]!;
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Distance in metres from a point to the nearest polygon edge (local flat projection). */
export function distanceToPolygonEdgeM(point: LatLng, polygon: LatLng[]): number {
  if (polygon.length === 0) return Infinity;
  const kLat = (Math.PI / 180) * EARTH_RADIUS_M;
  const kLng = kLat * Math.cos(toRad(point[0]));
  const proj = (p: LatLng): [number, number] => [(p[1] - point[1]) * kLng, (p[0] - point[0]) * kLat];
  let best = Infinity;
  for (let i = 0; i < polygon.length; i += 1) {
    const a = proj(polygon[i]!);
    const b = proj(polygon[(i + 1) % polygon.length]!);
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy;
    const u = len2 === 0 ? 0 : Math.max(0, Math.min(1, (-a[0] * dx - a[1] * dy) / len2));
    best = Math.min(best, Math.hypot(a[0] + u * dx, a[1] + u * dy));
  }
  return best;
}

export interface FenceShape {
  shape: 'circle' | 'polygon';
  center_lat: number | null;
  center_lng: number | null;
  radius_m: number | null;
  polygon: LatLng[];
  tolerance_m: number;
}

export interface FencePreview {
  inside: boolean;
  /** Metres beyond the fence edge (0 when inside). */
  distance_m: number;
}

/** Preview of a point against one fence, tolerance included. */
export function previewPoint(point: LatLng, fence: FenceShape): FencePreview | null {
  let inside: boolean;
  let outsideM: number;
  if (fence.shape === 'circle') {
    if (fence.center_lat == null || fence.center_lng == null || fence.radius_m == null) return null;
    outsideM = Math.max(0, haversineM(point, [fence.center_lat, fence.center_lng]) - fence.radius_m);
    inside = outsideM === 0;
  } else {
    if (fence.polygon.length < 3) return null;
    inside = pointInPolygon(point, fence.polygon);
    outsideM = inside ? 0 : distanceToPolygonEdgeM(point, fence.polygon);
  }
  const within = outsideM <= Math.max(0, fence.tolerance_m);
  return { inside: inside || within, distance_m: Math.round(outsideM) };
}

/** Closed GeoJSON ring ([lng, lat]) of any fence, or null when it is incomplete. */
export function fenceRing(fence: FenceShape): [number, number][] | null {
  if (fence.shape === 'circle') {
    if (fence.center_lat == null || fence.center_lng == null || !fence.radius_m) return null;
    return circlePolygon([fence.center_lat, fence.center_lng], fence.radius_m);
  }
  if (fence.polygon.length < 3) return null;
  const ring = fence.polygon.map(([lat, lng]) => [lng, lat] as [number, number]);
  ring.push(ring[0]!);
  return ring;
}

/** Radius in metres of the circle through the centre and a clicked edge point. */
export function radiusFromEdge(centre: LatLng, edge: LatLng): number {
  return Math.max(1, Math.round(haversineM(centre, edge)));
}
