/** Pixel-to-real-world scale conversion helpers */

export interface ScaleConfig {
  /** Pixels per real-world unit (e.g. pixels per meter) */
  pixelsPerUnit: number;
  /** Display unit label */
  unitLabel: string;
}

/** Common architectural scales */
export const COMMON_SCALES: { label: string; ratio: number }[] = [
  { label: '1:10', ratio: 10 },
  { label: '1:20', ratio: 20 },
  { label: '1:25', ratio: 25 },
  { label: '1:50', ratio: 50 },
  { label: '1:100', ratio: 100 },
  { label: '1:200', ratio: 200 },
  { label: '1:500', ratio: 500 },
  { label: '1:1000', ratio: 1000 },
];

/** Calculate distance between two points in pixels */
export function pixelDistance(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  return Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2);
}

/** Convert pixel distance to real-world distance */
export function toRealDistance(
  pixelDist: number,
  scale: ScaleConfig,
): number {
  if (scale.pixelsPerUnit <= 0) return 0;
  return pixelDist / scale.pixelsPerUnit;
}

/** Calculate area of a polygon (using shoelace formula) in pixel units */
export function polygonAreaPixels(points: { x: number; y: number }[]): number {
  if (points.length < 3) return 0;
  let area = 0;
  for (let i = 0; i < points.length; i++) {
    const j = (i + 1) % points.length;
    const pi = points[i]!;
    const pj = points[j]!;
    area += pi.x * pj.y;
    area -= pj.x * pi.y;
  }
  return Math.abs(area) / 2;
}

/** Convert pixel area to real-world area */
export function toRealArea(
  pixelArea: number,
  scale: ScaleConfig,
): number {
  if (scale.pixelsPerUnit <= 0) return 0;
  return pixelArea / (scale.pixelsPerUnit ** 2);
}

/** Calculate perimeter of a polygon in pixels */
export function polygonPerimeterPixels(
  points: { x: number; y: number }[],
): number {
  if (points.length < 2) return 0;
  let perimeter = 0;
  for (let i = 0; i < points.length; i++) {
    const j = (i + 1) % points.length;
    const pi = points[i]!;
    const pj = points[j]!;
    perimeter += pixelDistance(pi.x, pi.y, pj.x, pj.y);
  }
  return perimeter;
}

/** Format a measurement value with appropriate precision */
export function formatMeasurement(value: number, unit: string): string {
  if (value < 0.01) return `0 ${unit}`;
  if (value < 1) return `${value.toFixed(3)} ${unit}`;
  if (value < 100) return `${value.toFixed(2)} ${unit}`;
  return `${value.toFixed(1)} ${unit}`;
}

/** Derive scale from a known reference measurement.
 *  pixelLength = measured pixel distance on drawing
 *  realLength  = known real-world length in meters
 */
export function deriveScale(
  pixelLength: number,
  realLength: number,
): ScaleConfig {
  if (realLength <= 0 || pixelLength <= 0) {
    return { pixelsPerUnit: 1, unitLabel: 'm' };
  }
  return {
    pixelsPerUnit: pixelLength / realLength,
    unitLabel: 'm',
  };
}
