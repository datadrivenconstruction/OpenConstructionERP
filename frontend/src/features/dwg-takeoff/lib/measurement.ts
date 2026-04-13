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
