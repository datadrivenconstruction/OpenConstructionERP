/**
 * Measurement utilities for DWG takeoff annotations.
 */

/** Euclidean distance between two points. */
export function calculateDistance(
  p1: { x: number; y: number },
  p2: { x: number; y: number },
): number {
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/** Area of a polygon defined by ordered vertices (Shoelace formula). */
export function calculateArea(points: { x: number; y: number }[]): number {
  if (points.length < 3) return 0;
  let area = 0;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const pi = points[i]!;
    const pj = points[j]!;
    area += pi.x * pj.y;
    area -= pj.x * pi.y;
  }
  return Math.abs(area) / 2;
}

/** Format a measurement value with a unit label. */
export function formatMeasurement(value: number, unit: string): string {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)} k${unit}`;
  }
  if (value < 0.01) {
    return `${(value * 1000).toFixed(2)} m${unit}`;
  }
  return `${value.toFixed(2)} ${unit}`;
}

/* ── Polyline-specific measurements ──────────────────────────────── */

type Pt = { x: number; y: number };

/** Lengths of each segment in a polyline. */
export function getSegmentLengths(vertices: Pt[], closed = false): number[] {
  const lengths: number[] = [];
  for (let i = 0; i < vertices.length - 1; i++) {
    lengths.push(calculateDistance(vertices[i]!, vertices[i + 1]!));
  }
  if (closed && vertices.length >= 3) {
    lengths.push(calculateDistance(vertices[vertices.length - 1]!, vertices[0]!));
  }
  return lengths;
}

/** Total perimeter (sum of segment lengths). */
export function calculatePerimeter(vertices: Pt[], closed = false): number {
  return getSegmentLengths(vertices, closed).reduce((a, b) => a + b, 0);
}

/** Midpoint of a segment (for label placement). */
export function segmentMidpoint(a: Pt, b: Pt): Pt {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/** Minimum distance from a point to a line segment AB. */
export function pointToSegmentDistance(p: Pt, a: Pt, b: Pt): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return calculateDistance(p, a); // degenerate segment
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  const proj = { x: a.x + t * dx, y: a.y + t * dy };
  return calculateDistance(p, proj);
}

/** Centroid of a polygon (for area label placement). */
export function polygonCentroid(vertices: Pt[]): Pt {
  let cx = 0, cy = 0;
  for (const v of vertices) { cx += v.x; cy += v.y; }
  return { x: cx / vertices.length, y: cy / vertices.length };
}
