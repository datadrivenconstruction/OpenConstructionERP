// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure helpers for drawing on the site plan. Everything is in metres of the
// site's local frame with y pointing up; the screen's y points down, so the
// drawing flips it. Areas and overlaps are the server's to compute: nothing
// here measures a polygon.

/** A point in metres of the local site frame: [x, y], y up. */
export type Pt = readonly [number, number];

export interface Polygon {
  type: 'Polygon';
  coordinates: number[][][];
}
export interface LineString {
  type: 'LineString';
  coordinates: number[][];
}
export interface PointGeometry {
  type: 'Point';
  coordinates: number[];
}

/** The part of the site the drawing shows, in metres. */
export interface View {
  minX: number;
  minY: number;
  width: number;
  height: number;
}

export interface Calibration {
  metresPerPixel: number;
  /** The pixel of the plan image that is the origin of the metre frame. */
  origin: Pt;
}

/** Centimetres are as fine as a site plan gets. */
export function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

function same(a: Pt, b: Pt): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

function isPt(raw: unknown): raw is [number, number] {
  return Array.isArray(raw) && raw.length >= 2 && Number.isFinite(raw[0]) && Number.isFinite(raw[1]);
}

function points(raw: unknown): Pt[] {
  return Array.isArray(raw) ? raw.filter(isPt).map((p) => [p[0], p[1]] as const) : [];
}

/* ── Scale ────────────────────────────────────────────────────────────── */

/** Metres per pixel from two clicked pixels and the real distance between them; null when that says nothing. */
export function metresPerPixel(a: Pt, b: Pt, distanceM: number): number | null {
  const pixels = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (!(pixels > 0) || !(distanceM > 0) || !Number.isFinite(distanceM)) return null;
  return distanceM / pixels;
}

export function imageToMetres(px: Pt, c: Calibration): Pt {
  return [round2((px[0] - c.origin[0]) * c.metresPerPixel), round2((c.origin[1] - px[1]) * c.metresPerPixel)];
}

export function metresToImage(m: Pt, c: Calibration): Pt {
  return [c.origin[0] + m[0] / c.metresPerPixel, c.origin[1] - m[1] / c.metresPerPixel];
}

/* ── Outlines, routes, points ─────────────────────────────────────────── */

/** A GeoJSON polygon from the clicked corners: repeated corners dropped, the ring closed. Null below three corners. */
export function closeRing(corners: readonly Pt[]): Polygon | null {
  const ring: Pt[] = [];
  for (const p of corners) {
    const last = ring[ring.length - 1];
    if (!last || !same(last, p)) ring.push(p);
  }
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first && last && ring.length > 1 && same(first, last)) ring.pop();
  if (ring.length < 3 || !first) return null;
  return { type: 'Polygon', coordinates: [[...ring, first].map((p) => [round2(p[0]), round2(p[1])])] };
}

/** The corners of a stored polygon's outer ring, without the closing repeat. Empty for anything else. */
export function openRing(geometry: unknown): Pt[] {
  const g = geometry as { type?: unknown; coordinates?: unknown } | null | undefined;
  if (!g || g.type !== 'Polygon' || !Array.isArray(g.coordinates)) return [];
  const ring = points(g.coordinates[0]);
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first && last && ring.length > 1 && same(first, last)) ring.pop();
  return ring;
}

export function toLine(route: readonly Pt[]): LineString | null {
  if (route.length < 2) return null;
  return { type: 'LineString', coordinates: route.map((p) => [round2(p[0]), round2(p[1])]) };
}

export function linePoints(geometry: unknown): Pt[] {
  const g = geometry as { type?: unknown; coordinates?: unknown } | null | undefined;
  return g && g.type === 'LineString' ? points(g.coordinates) : [];
}

export function toPoint(p: Pt): PointGeometry {
  return { type: 'Point', coordinates: [round2(p[0]), round2(p[1])] };
}

export function pointOf(geometry: unknown): Pt | null {
  const g = geometry as { type?: unknown; coordinates?: unknown } | null | undefined;
  return g && g.type === 'Point' && isPt(g.coordinates) ? [g.coordinates[0], g.coordinates[1]] : null;
}

/* ── Editing ──────────────────────────────────────────────────────────── */

export function moveVertex(list: readonly Pt[], index: number, to: Pt): Pt[] {
  return list.map((p, i) => (i === index ? ([round2(to[0]), round2(to[1])] as const) : p));
}

/** Without the vertex; unchanged when that would leave fewer than `min`. */
export function removeVertex(list: readonly Pt[], index: number, min: number): Pt[] {
  if (list.length <= min || index < 0 || index >= list.length) return [...list];
  return list.filter((_, i) => i !== index);
}

/* ── Screen ───────────────────────────────────────────────────────────── */

const EMPTY_VIEW: View = { minX: 0, minY: 0, width: 100, height: 60 };

/** A view that holds every shape with a margin; a 100 by 60 metre sheet when there is nothing yet. */
export function viewOf(shapes: readonly (readonly Pt[])[], margin = 0.1): View {
  const all = shapes.flat();
  if (all.length === 0) return EMPTY_VIEW;
  const xs = all.map((p) => p[0]);
  const ys = all.map((p) => p[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  // A single point or a straight line still needs a sheet around it.
  const width = Math.max(Math.max(...xs) - minX, 20);
  const height = Math.max(Math.max(...ys) - minY, 20);
  const pad = Math.max(width, height) * margin;
  return { minX: minX - pad, minY: minY - pad, width: width + 2 * pad, height: height + 2 * pad };
}

/** The svg viewBox of a view: x as is, y flipped. */
export function viewBox(v: View): string {
  return `${v.minX} ${-(v.minY + v.height)} ${v.width} ${v.height}`;
}

/** `points` attribute of a polyline or polygon, y flipped. */
export function svgPoints(list: readonly Pt[]): string {
  return list.map((p) => `${p[0]},${-p[1]}`).join(' ');
}

/**
 * Where a click landed, in metres. The drawing keeps its proportions inside
 * the element (as `xMidYMid meet` does), so one scale serves both axes and
 * the spare room is split evenly. An element without a size, as in a test
 * without layout, counts as one pixel per metre.
 */
export function screenToMetres(
  client: Pt,
  rect: { left: number; top: number; width: number; height: number },
  view: View,
): Pt {
  const sized = rect.width > 0 && rect.height > 0;
  const scale = sized ? Math.max(view.width / rect.width, view.height / rect.height) : 1;
  const spareX = sized ? (rect.width * scale - view.width) / 2 : 0;
  const spareY = sized ? (rect.height * scale - view.height) / 2 : 0;
  const x = view.minX + (client[0] - rect.left) * scale - spareX;
  const y = view.minY + view.height - ((client[1] - rect.top) * scale - spareY);
  return [round2(x), round2(y)];
}

/** Metres one screen pixel covers; one when the element has no size. */
export function screenScale(rect: { width: number; height: number }, view: View): number {
  return rect.width > 0 && rect.height > 0 ? Math.max(view.width / rect.width, view.height / rect.height) : 1;
}

const NARROWEST_M = 1;
const WIDEST_M = 1e6;

/** The view scaled by `factor` (below one zooms in) so that `about` stays where it is on screen. */
export function zoomView(view: View, factor: number, about: Pt): View {
  const widest = Math.max(view.width, view.height);
  const f = Math.min(Math.max(factor, NARROWEST_M / widest), WIDEST_M / widest);
  return {
    minX: about[0] - (about[0] - view.minX) * f,
    minY: about[1] - (about[1] - view.minY) * f,
    width: view.width * f,
    height: view.height * f,
  };
}

/** The view moved by metres. */
export function panView(view: View, dx: number, dy: number): View {
  return { ...view, minX: view.minX + dx, minY: view.minY + dy };
}

export function centre(list: readonly Pt[]): Pt | null {
  if (list.length === 0) return null;
  return [list.reduce((s, p) => s + p[0], 0) / list.length, list.reduce((s, p) => s + p[1], 0) / list.length];
}
