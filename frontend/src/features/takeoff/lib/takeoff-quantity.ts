// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Effective-quantity math for takeoff measurements.
 *
 * A raw measurement carries the geometry it was drawn at (plan length / area /
 * volume / count). The number an estimator actually reports can differ from
 * that geometry for three additive, opt-in reasons:
 *
 *   - slope / pitch  (area only): a sloped roof or ramp covers more true
 *                    surface than its plan projection, so the reported area is
 *                    `plan area x slopeFactor` (>= 1).
 *   - wastage %      : materials are ordered with an allowance on top of the
 *                    net quantity (cut waste, laps, breakage).
 *   - multiplier     : a "typical" detail repeats N times (typical floors,
 *                    identical bays) so one drawn shape stands for N.
 *
 * A LINEAR measurement (distance / polyline) can also carry a wall height.
 * It then reports wall AREA instead of length: `length x height`, minus the
 * openings entered on it (`width x height x count` each), clamped at zero,
 * and only then scaled by wastage and the multiplier (a typical floor repeats
 * its openings too). The unit follows: a wall in `m` reports `m²`, see
 * {@link effectiveUnit}. Openings live on the wall row rather than as separate
 * deduction rows because the BOQ push is per measurement: only the wall row
 * itself can carry its net figure into a linked position.
 *
 * Every field is optional and its default is the identity value, so a
 * measurement with none of them set reports exactly its raw value - this whole
 * module is a no-op for existing data.
 *
 * {@link effectiveQuantity} is the SINGLE place this folding happens (plus the
 * opening-deduction sign) so the ledger, legend, exports and the linked-BOQ
 * push all report the same figure. It is pure + dependency-free (only the
 * shared Measurement type), so it unit-tests without React or pdf.js.
 */

import type { Measurement, WallOpening } from './takeoff-types';

/**
 * Clamp a user-entered slope/pitch FACTOR to a sane, finite multiplier.
 * A factor is dimensionless and never less than 1 (a slope only adds surface);
 * non-finite or <= 0 input falls back to 1 (flat, no change).
 */
export function normalizeSlopeFactor(raw: number | undefined | null): number {
  if (raw == null || !Number.isFinite(raw) || raw < 1) return 1;
  return raw;
}

/**
 * Convert a roof / ramp pitch in DEGREES to its plan -> true-surface area
 * factor, `1 / cos(deg)`. A flat 0 degrees gives 1; a 45 degree pitch gives
 * ~1.414. Guarded: input is clamped to (-89, 89) degrees so `cos` never
 * approaches 0 (an infinite factor), and any non-finite result falls back to
 * 1.
 */
export function slopeFactorFromDegrees(deg: number): number {
  if (!Number.isFinite(deg)) return 1;
  const clamped = Math.max(-89, Math.min(89, deg));
  const f = 1 / Math.cos((clamped * Math.PI) / 180);
  return Number.isFinite(f) && f >= 1 ? f : 1;
}

/**
 * Inverse of {@link slopeFactorFromDegrees}: the pitch in degrees that a given
 * factor corresponds to, `acos(1 / factor)`. Used to pre-fill the degrees
 * input from a stored factor. A factor <= 1 maps to 0 degrees (flat).
 */
export function degreesFromSlopeFactor(factor: number): number {
  if (!Number.isFinite(factor) || factor <= 1) return 0;
  const deg = (Math.acos(1 / factor) * 180) / Math.PI;
  return Number.isFinite(deg) ? deg : 0;
}

/**
 * Normalize the typical-multiplier to a positive integer count of repeats.
 * Non-finite or < 1 falls back to 1; a fractional value is floored (you cannot
 * have 2.5 typical floors).
 */
export function normalizeMultiplier(raw: number | undefined | null): number {
  if (raw == null || !Number.isFinite(raw)) return 1;
  const n = Math.floor(raw);
  return n >= 1 ? n : 1;
}

/**
 * Normalize the wastage / allowance percent (>= 0). Non-finite or negative
 * falls back to 0 (no allowance).
 */
export function normalizeWastagePct(raw: number | undefined | null): number {
  if (raw == null || !Number.isFinite(raw) || raw < 0) return 0;
  return raw;
}

/**
 * Unitless multiplier folding slope (area only), wastage and the typical
 * multiplier. Always finite and > 0. Returns exactly 1 when nothing is set, so
 * `value x quantityFactor(m)` equals the raw value (zero behaviour change).
 */
export function quantityFactor(m: Measurement): number {
  const slope = m.type === 'area' ? normalizeSlopeFactor(m.slopeFactor) : 1;
  const waste = 1 + normalizeWastagePct(m.wastagePct) / 100;
  const mult = normalizeMultiplier(m.multiplier);
  return slope * waste * mult;
}

/**
 * Normalize a wall height (canonical metres). Non-finite or <= 0 means "no
 * height", returned as 0, which leaves the measurement a plain length.
 */
export function normalizeWallHeight(raw: number | undefined | null): number {
  if (raw == null || !Number.isFinite(raw) || raw <= 0) return 0;
  return raw;
}

/** Whether a measurement is linear, i.e. measures a run in metres. */
export function isLinearMeasurement(m: Pick<Measurement, 'type'>): boolean {
  return m.type === 'distance' || m.type === 'polyline';
}

/**
 * Whether a measurement reports wall area: a linear run with a wall height
 * set. Every other measurement keeps its legacy behaviour.
 */
export function isWallMeasurement(m: Pick<Measurement, 'type' | 'wallHeight'>): boolean {
  return isLinearMeasurement(m) && normalizeWallHeight(m.wallHeight) > 0;
}

/**
 * Normalize one opening: width and height are finite and >= 0 (else 0); the
 * count is a whole number >= 0, and a missing / non-finite count means one
 * opening, since an entry the user typed stands for at least itself.
 */
export function normalizeOpening(o: Partial<WallOpening> | null | undefined): WallOpening {
  const dim = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0);
  const rawCount = o?.count;
  const count =
    typeof rawCount === 'number' && Number.isFinite(rawCount) ? Math.max(0, Math.floor(rawCount)) : 1;
  return { width: dim(o?.width), height: dim(o?.height), count };
}

/** Area of one opening entry, `width x height x count`, in m². */
export function openingArea(o: Partial<WallOpening> | null | undefined): number {
  const n = normalizeOpening(o);
  return n.width * n.height * n.count;
}

/** Total opening area entered on a wall (m²). 0 when it is not a wall. */
export function wallOpeningsArea(m: Pick<Measurement, 'type' | 'wallHeight' | 'openings'>): number {
  if (!isWallMeasurement(m) || !Array.isArray(m.openings)) return 0;
  return m.openings.reduce((sum, o) => sum + openingArea(o), 0);
}

/** Total number of openings on a wall (sum of the entry counts). */
export function wallOpeningsCount(m: Pick<Measurement, 'type' | 'wallHeight' | 'openings'>): number {
  if (!isWallMeasurement(m) || !Array.isArray(m.openings)) return 0;
  return m.openings.reduce((sum, o) => sum + normalizeOpening(o).count, 0);
}

/** Gross wall area, `length x height` (m²), before openings. 0 when it is not a wall. */
export function wallGrossArea(m: Pick<Measurement, 'type' | 'wallHeight' | 'value'>): number {
  if (!isWallMeasurement(m)) return 0;
  const length = Number.isFinite(m.value) ? m.value : 0;
  return length * normalizeWallHeight(m.wallHeight);
}

/** Net wall area before wastage / multiplier: gross minus openings, never below 0. */
export function wallNetArea(m: Pick<Measurement, 'type' | 'wallHeight' | 'value' | 'openings'>): number {
  return Math.max(0, wallGrossArea(m) - wallOpeningsArea(m));
}

/**
 * True when the openings entered on a wall add up to more than the wall
 * itself. The reported quantity is clamped at 0 in that case, which would hide
 * the size of the mistake, so the UI asks this separately and warns.
 */
export function openingsExceedGross(m: Pick<Measurement, 'type' | 'wallHeight' | 'value' | 'openings'>): boolean {
  return isWallMeasurement(m) && wallOpeningsArea(m) > wallGrossArea(m) + 1e-9;
}

/**
 * Unit of the REPORTED quantity. Equals the stored unit, except for a wall,
 * whose length unit becomes the matching area unit (`m` -> `m²`). Every surface
 * that prints or buckets {@link effectiveQuantity} pairs it with this, never
 * with `m.unit`, or a wall's m² would be summed into metres.
 */
export function effectiveUnit(m: Pick<Measurement, 'type' | 'wallHeight' | 'unit'>): string {
  if (!isWallMeasurement(m)) return m.unit;
  const base = (m.unit || 'm').replace(/[²2]$/, '');
  return `${base}²`;
}

/**
 * The measurement type a row is TOTALLED under. A wall reports area, so it
 * sums with areas; every other row keeps its own type.
 */
export function reportingType(m: Pick<Measurement, 'type' | 'wallHeight'>): Measurement['type'] {
  return isWallMeasurement(m) ? 'area' : m.type;
}

/**
 * Whether a measurement's reported quantity differs from its raw geometry:
 * an active slope / wastage / multiplier factor, or a wall height (which turns
 * a length into an area). Uses a small tolerance so float noise in the slope
 * factor does not read as "adjusted". The link flow keys on this: the server
 * push copies the RAW stored value, so an adjusted row must not be pushed.
 */
export function hasQuantityFactor(m: Measurement): boolean {
  return isWallMeasurement(m) || Math.abs(quantityFactor(m) - 1) > 1e-9;
}

/**
 * Signed reported quantity for a measurement: the raw measured value (or the
 * net wall area for a wall) scaled by {@link quantityFactor}, negated when the
 * measurement is an opening deduction (area void, so net = gross - openings).
 * This is the single source of truth for the figure shown per-row in the
 * ledger, summed into subtotals / grand totals / the legend, written into
 * exports, and pushed to a linked BOQ position - so every surface reports the
 * same number.
 */
export function effectiveQuantity(m: Measurement): number {
  const base = isWallMeasurement(m) ? wallNetArea(m) : Number.isFinite(m.value) ? m.value : 0;
  const magnitude = base * quantityFactor(m);
  return m.isDeduction ? -magnitude : magnitude;
}

/**
 * The POSITIVE reported quantity (magnitude of {@link effectiveQuantity}),
 * used where a sign makes no sense - above all the linked-BOQ push, since a
 * BOQ position quantity is always positive. Equals the raw value when no
 * factor is set.
 */
export function reportedMagnitude(m: Measurement): number {
  return Math.abs(effectiveQuantity(m));
}

/**
 * A short, human-readable summary of the active adjustments on a measurement,
 * e.g. `"x3"`, `"+10%"`, `"pitch 1.05"`, or a combination `"x3 +10%"`. Empty
 * string when nothing is set. Rendered as a compact badge next to the value in
 * the ledger / sidebar so a reported number that differs from the drawn
 * geometry is never a mystery.
 */
export function quantityAdjustmentLabel(m: Measurement): string {
  const parts: string[] = [];
  const mult = normalizeMultiplier(m.multiplier);
  if (mult !== 1) parts.push(`x${mult}`);
  const waste = normalizeWastagePct(m.wastagePct);
  if (waste > 0) parts.push(`+${Number(waste.toFixed(2))}%`);
  if (m.type === 'area') {
    const slope = normalizeSlopeFactor(m.slopeFactor);
    if (slope !== 1) parts.push(`pitch ${Number(slope.toFixed(3))}`);
  }
  return parts.join(' ');
}
