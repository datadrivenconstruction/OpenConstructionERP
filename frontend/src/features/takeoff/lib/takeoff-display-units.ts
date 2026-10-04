// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Takeoff display-unit conversion.
 *
 * Takeoff measurements are stored metric-canonical (D-TKC-016: every
 * stored `unitLabel` is "m" and the value is metres / m2 / m3), regardless
 * of how the estimator calibrated the drawing. This module is the single
 * seam that converts those canonical metric quantities into the user's
 * preferred measurement system *at the display / export boundary only* -
 * storage is never touched.
 *
 * It is a thin wrapper over the shared `convertUnit` / `getDisplayUnit`
 * helpers (the same mechanism `QuantityDisplay` uses) so the rounding and
 * unit labels stay consistent across the whole app:
 *   - `metric`   : value + unit are returned unchanged (so a metric user
 *                  sees byte-identical output to before this seam existed).
 *   - `imperial` : m -> ft, m2/m² -> ft², m3/m³ -> ft³.
 *
 * The conversion is done here; the *formatting* (precision rules) is left
 * to each caller's existing formatter so that the metric path is provably
 * unchanged - we only feed a converted number + converted label through the
 * formatter that was already in place.
 */

import type { MeasurementSystem } from '@/stores/usePreferencesStore';
import { convertUnit, getDisplayUnit } from '@/shared/lib/unitConversion';
import type { Measurement } from './takeoff-types';
import { effectiveQuantity, effectiveUnit, isWallMeasurement, wallGrossArea } from './takeoff-quantity';
import {
  type ScaleConfig,
  formatFeetInches,
  formatMeasurement,
  polygonPerimeterPixels,
  toRealDistance,
} from '@/modules/pdf-takeoff/data/scale-helpers';

export interface DisplayQuantity {
  /** Numeric value in the target system (unchanged when metric). */
  value: number;
  /** Display-friendly unit label in the target system. */
  unit: string;
}

/**
 * Convert a metric-canonical quantity into the target measurement system.
 *
 * For `metric` the value passes through untouched and the unit is only
 * normalised to its display form (e.g. "m2" -> "m²"). For `imperial` the
 * value is scaled and the unit relabelled (m -> ft, m² -> ft², m³ -> ft³).
 * Units with no imperial mapping (pcs, lsum, ...) pass through unchanged in
 * both systems, which is the correct behaviour for countable / lump items.
 */
export function convertQuantity(
  value: number,
  metricUnit: string,
  system: MeasurementSystem,
): DisplayQuantity {
  if (system !== 'imperial') {
    // Metric: never scale; keep the value bit-for-bit and only tidy the
    // unit label so "m2"/"m3" render as "m²"/"m³" like the rest of the UI.
    return { value, unit: getDisplayUnit(metricUnit) };
  }
  const result = convertUnit(value, metricUnit, 'imperial');
  return { value: result.value, unit: result.displayUnit };
}

/**
 * The display unit label a metric unit resolves to in the target system,
 * without needing a value. Used where only the unit column / suffix is
 * rendered (e.g. a calibration depth-input suffix or a ledger unit cell).
 */
export function displayUnitFor(
  metricUnit: string,
  system: MeasurementSystem,
): string {
  return convertQuantity(0, metricUnit, system).unit;
}

/**
 * Convert only the value of a metric quantity to the target system,
 * discarding the label. Handy for export sheets that store a raw numeric
 * cell + a separate unit string.
 */
export function convertValue(
  value: number,
  metricUnit: string,
  system: MeasurementSystem,
): number {
  return convertQuantity(value, metricUnit, system).value;
}

/**
 * Format a single converted quantity the way the on-canvas / readout labels
 * do (via `formatMeasurement`), in the target system. For `metric` this is
 * exactly `formatMeasurement(value, getDisplayUnit(metricUnit))`.
 */
export function formatQuantity(
  value: number,
  metricUnit: string,
  system: MeasurementSystem,
): string {
  const d = convertQuantity(value, metricUnit, system);
  // A LINEAR dimension in the imperial system is written the way it is written
  // on a drawing: 12'-6 3/4", not 41.01 ft. Only the linear case. Nobody
  // dimensions a slab as four hundred square feet and three quarters, so area
  // and volume keep decimal ft² / ft³ and fall through to the shared
  // formatter. `d.unit` is the seam that tells the two apart, because it is
  // already the result of the metric-to-imperial mapping.
  //
  // `value` rather than `d.value` is passed on purpose: formatFeetInches takes
  // metres and does its own conversion, in integer sixteenths. Handing it the
  // already-converted decimal feet would convert twice and reintroduce exactly
  // the float rounding the integer path exists to avoid.
  if (system === 'imperial' && d.unit === 'ft') {
    return formatFeetInches(value);
  }
  return formatMeasurement(d.value, d.unit);
}

/**
 * Recompute the on-canvas value label for a measurement in the target
 * measurement system.
 *
 * Takeoff stores quantities in metres (D-TKC-016) and this recomputes
 * the label from `value` + geometry through the same `formatMeasurement`
 * rules used at create time. Since K-12 the digits render in the READER's
 * app language, so the recomputed string equals a string the author saw
 * only when their locales agree - which is why quantity labels are no
 * longer persisted into `annotation` (K-13, see
 * `useMeasurementPersistence.annotationForWire`): display is always
 * recomputed, never read back from a stored render. For `imperial` the
 * label is rebuilt with converted numbers + ft / ft² / ft³ units. Counts
 * and annotation markups carry no convertible quantity, so their stored
 * label / annotation is returned untouched.
 *
 * The compound area / volume breakdowns mirror the create-time formats:
 *   area   -> "{area} u² (P: {perimeter} u)"
 *   volume -> "V = {vol} u³ (A: {base} u² x D: {depth} u)"
 * Perimeter is recomputed from the polygon points + `scale` (it is not a
 * stored field); base area + depth come from the stored measurement.
 */
export function measurementLabel(
  m: Measurement,
  scale: ScaleConfig,
  system: MeasurementSystem,
): string {
  switch (m.type) {
    case 'distance':
    case 'polyline': {
      // Stored unit is "m"; value is metres.
      const lengthStr = formatQuantity(m.value, m.unit || 'm', system);
      if (!isWallMeasurement(m)) return lengthStr;
      // A wall reads as its sum, "12.5 m × 2.8 m = 35 m²", and when openings,
      // wastage or a multiplier move the reported figure, "→ 31.2 m²" after it,
      // so the drawing shows the same number the ledger and the bill carry.
      const areaUnit = effectiveUnit(m);
      const heightStr = formatQuantity(m.wallHeight ?? 0, m.unit || 'm', system);
      const gross = wallGrossArea(m);
      const reported = Math.abs(effectiveQuantity(m));
      const head = `${lengthStr} × ${heightStr} = ${formatQuantity(gross, areaUnit, system)}`;
      return Math.abs(reported - gross) > 1e-9
        ? `${head} → ${formatQuantity(reported, areaUnit, system)}`
        : head;
    }

    case 'area': {
      const areaStr = formatQuantity(m.value, m.unit || 'm²', system);
      const perimMetres = toRealDistance(
        polygonPerimeterPixels(m.points),
        scale,
      );
      const perimStr = formatQuantity(perimMetres, 'm', system);
      return `${areaStr} (P: ${perimStr})`;
    }

    case 'volume': {
      const volStr = formatQuantity(m.value, m.unit || 'm³', system);
      const baseArea = m.area ?? 0;
      const baseStr = formatQuantity(baseArea, 'm²', system);
      const depthStr = formatQuantity(m.depth ?? 0, 'm', system);
      return `V = ${volStr} (A: ${baseStr} × D: ${depthStr})`;
    }

    case 'count':
      // Counts render as the annotation plus a live tally of placed points,
      // mirroring the on-canvas and PDF / Excel export renderers. The tally
      // lives in m.points.length (kept in sync with m.value); the stored label
      // is the static group label and would show no tally (issue #300).
      return `${m.annotation} (${m.points.length})`;

    default:
      // Annotation markups (cloud / arrow / text / rectangle / highlight): no
      // convertible quantity - keep the stored label.
      return m.label;
  }
}
