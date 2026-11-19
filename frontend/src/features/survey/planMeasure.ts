// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Measuring on the survey plan. A vertex snapped to a survey point carries the
 * point's grid E/N, and when every vertex is snapped the result is exact on the
 * project grid; otherwise it is a ground estimate from WGS 84.
 */

import type { Feature } from 'geojson';

export interface Vertex {
  lon: number;
  lat: number;
  e?: number;
  n?: number;
  label?: string;
}

export interface Measure {
  distance_m: number;
  area_m2: number | null;
  exact: boolean;
}

const R = 6371008.8;
const rad = (d: number) => (d * Math.PI) / 180;

export function haversine(a: Vertex, b: Vertex): number {
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Nearest survey point within `radiusM` of the click, as a vertex with its grid coordinates. */
export function snapToPoint(click: Vertex, points: Feature[], radiusM: number): Vertex {
  let best: Vertex | null = null;
  let bestD = radiusM;
  for (const f of points) {
    if (f.geometry?.type !== 'Point') continue;
    const [lon, lat] = f.geometry.coordinates as [number, number];
    const p = f.properties ?? {};
    const cand: Vertex = { lon, lat, e: p.e, n: p.n, label: p.id };
    const d = haversine(click, cand);
    if (d <= bestD) {
      bestD = d;
      best = cand;
    }
  }
  return best ?? click;
}

function shoelace(xy: [number, number][]): number {
  let s = 0;
  for (let i = 0; i < xy.length; i++) {
    const [x1, y1] = xy[i]!;
    const [x2, y2] = xy[(i + 1) % xy.length]!;
    s += x1 * y2 - x2 * y1;
  }
  return Math.abs(s) / 2;
}

/** Path length, and the enclosed area when `closed` and there are three vertices or more. */
export function measure(vertices: Vertex[], closed: boolean): Measure {
  const exact = vertices.length > 0 && vertices.every((v) => v.e != null && v.n != null);
  const ring = closed && vertices.length >= 3 ? [...vertices, vertices[0]!] : vertices;
  let distance = 0;
  for (let i = 1; i < ring.length; i++) {
    const a = ring[i - 1]!;
    const b = ring[i]!;
    distance += exact ? Math.hypot(b.e! - a.e!, b.n! - a.n!) : haversine(a, b);
  }
  let area: number | null = null;
  if (closed && vertices.length >= 3) {
    if (exact) {
      area = shoelace(vertices.map((v) => [v.e!, v.n!]));
    } else {
      const lat0 = rad(vertices.reduce((s, v) => s + v.lat, 0) / vertices.length);
      area = shoelace(vertices.map((v) => [rad(v.lon) * R * Math.cos(lat0), rad(v.lat) * R]));
    }
  }
  return { distance_m: distance, area_m2: area, exact };
}

/** The drawn path as plan features: vertices plus a line, or a polygon when closed. */
export function measureFeatures(vertices: Vertex[], closed: boolean): Feature[] {
  const coords: [number, number][] = vertices.map((v) => [v.lon, v.lat]);
  const out: Feature[] = coords.map((c) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: c }, properties: {} }));
  if (closed && coords.length >= 3) {
    out.push({ type: 'Feature', geometry: { type: 'Polygon', coordinates: [[...coords, coords[0]!]] }, properties: {} });
  } else if (coords.length >= 2) {
    out.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: {} });
  }
  return out;
}
