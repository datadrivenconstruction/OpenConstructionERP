/**
 * Two-click scale calibration for DWG takeoff.
 *
 * The raw DXF canvas is addressed in pixels (world-space "units", really,
 * but at the UI layer estimators think in pixels). Calibration turns those
 * pixels into real-world units by asking the user: "you clicked two
 * points — what's the physical distance between them?" We then compute
 * ``unitsPerPixel = realDistance / pixelDistance`` and every subsequent
 * distance / line / polyline / area / circle measurement is labelled in
 * the chosen unit.
 *
 * This module is intentionally small and framework-free — the UI layer
 * (CalibrationDialog) wraps the math with the two-step click flow, and the
 * store layer (calibration-store.ts) persists the result per-layout.
 * Unifying this with the PDF takeoff module's ``deriveScale`` helper is
 * tracked separately; see the task brief note.
 */

export type CalibrationUnit = 'm' | 'mm' | 'ft' | 'in';

/** Ordered list surfaced by the unit dropdown — metric first, imperial
 *  after, matching the rest of the app's default UI. */
export const CALIBRATION_UNITS: CalibrationUnit[] = ['m', 'mm', 'ft', 'in'];

/** Snapshot persisted per drawing+layout. ``pointA``/``pointB`` are kept
 *  so the UI can redraw the calibration reference line as a reminder
 *  ("this is what you calibrated against") even across reloads. */
export interface CalibrationState {
  unitsPerPixel: number;
  unit: CalibrationUnit;
  calibratedAt: number;
  pointA?: [number, number];
  pointB?: [number, number];
}

/** Thrown when the two clicks coincide — no scale can be derived from
 *  a zero-length reference. Callers convert this to an inline error
 *  message in the modal. */
export class ZeroPixelDistanceError extends Error {
  constructor() {
    super('Pixel distance between calibration points is zero');
    this.name = 'ZeroPixelDistanceError';
  }
}

/** Unit → metres conversion factor. Exact for SI units; the imperial
 *  conversions use the internationally accepted definitions (1 ft =
 *  0.3048 m exactly, 1 in = 0.0254 m exactly). */
const UNIT_TO_METRES: Record<CalibrationUnit, number> = {
  m: 1,
  mm: 0.001,
  ft: 0.3048,
  in: 0.0254,
};

/** Convert ``value`` from ``unit`` to metres. Purely multiplicative —
 *  no translation / zero-offset involved. */
export function toMeters(value: number, unit: CalibrationUnit): number {
  return value * UNIT_TO_METRES[unit];
}

/** Convert ``metres`` to ``unit``. Inverse of ``toMeters``. */
export function fromMeters(metres: number, unit: CalibrationUnit): number {
  return metres / UNIT_TO_METRES[unit];
}

/** Euclidean distance helper. Exported so the dialog can display the
 *  pixel distance in Step 3 without pulling in the full measurement
 *  module (which has extra area / perimeter helpers we don't need). */
export function pixelDistance(
  a: readonly [number, number] | { x: number; y: number },
  b: readonly [number, number] | { x: number; y: number },
): number {
  const ax = Array.isArray(a) ? a[0] : (a as { x: number }).x;
  const ay = Array.isArray(a) ? a[1] : (a as { y: number }).y;
  const bx = Array.isArray(b) ? b[0] : (b as { x: number }).x;
  const by = Array.isArray(b) ? b[1] : (b as { y: number }).y;
  return Math.hypot(bx - ax, by - ay);
}

/**
 * Derive a calibration from two clicked points and a user-entered real
 * distance. Returns the ratio "real units per pixel" plus the chosen unit
 * label — both consumed by ``formatWithUnit`` on every subsequent render.
 *
 * Throws ``ZeroPixelDistanceError`` if the two points coincide (which would
 * make the ratio infinite) or if the user types a zero / negative real
 * length (which is never a valid physical distance).
 */
export function deriveScale(
  pointA: readonly [number, number] | { x: number; y: number },
  pointB: readonly [number, number] | { x: number; y: number },
  realLength: number,
  realUnit: CalibrationUnit,
): { unitsPerPixel: number; unit: CalibrationUnit } {
  const pixels = pixelDistance(pointA, pointB);
  if (!Number.isFinite(pixels) || pixels <= 0) {
    throw new ZeroPixelDistanceError();
  }
  if (!Number.isFinite(realLength) || realLength <= 0) {
    throw new ZeroPixelDistanceError();
  }
  return {
    unitsPerPixel: realLength / pixels,
    unit: realUnit,
  };
}

/**
 * Format a pixel-space length using the active calibration. When ``scale``
 * is null the caller has no calibration yet — we fall back to showing the
 * raw pixel count with an "(uncal)" hint so the estimator knows the number
 * is preliminary and won't confuse it with a real dimension.
 *
 * Precision follows the convention used elsewhere in the page: two
 * decimals for "normal" magnitudes, three for sub-unit values. Feet/inches
 * use the same rule — we don't fractional-inch format because that's an
 * opinionated UX choice best left to the unified pipeline.
 */
export function formatWithUnit(
  pixels: number,
  scale: { unitsPerPixel: number; unit: CalibrationUnit } | null | undefined,
): string {
  if (!scale) {
    return `${pixels.toFixed(1)} px (uncal)`;
  }
  const value = pixels * scale.unitsPerPixel;
  return `${formatNumeric(value)} ${scale.unit}`;
}

/**
 * Format an area-style value (pixels²) using the active calibration.
 * Same precision rules as ``formatWithUnit`` but with a squared unit
 * suffix (e.g. ``m²``, ``ft²``).
 */
export function formatAreaWithUnit(
  pixelsSquared: number,
  scale: { unitsPerPixel: number; unit: CalibrationUnit } | null | undefined,
): string {
  if (!scale) {
    return `${pixelsSquared.toFixed(0)} px\u00B2 (uncal)`;
  }
  const value = pixelsSquared * scale.unitsPerPixel * scale.unitsPerPixel;
  return `${formatNumeric(value)} ${scale.unit}\u00B2`;
}

/** Shared numeric formatter so distances / areas line up. Matches the
 *  page-level ``formatMeasurement`` precision policy. */
function formatNumeric(value: number): string {
  if (value >= 1000) return (value / 1000).toFixed(2) + 'k';
  if (value < 0.01) return value.toFixed(4);
  if (value < 1) return value.toFixed(3);
  return value.toFixed(2);
}
