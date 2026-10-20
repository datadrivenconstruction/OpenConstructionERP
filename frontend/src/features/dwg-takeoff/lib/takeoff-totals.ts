// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One computation for every DWG takeoff number the user can read.
 *
 * Drawing units come from the DXF header ($INSUNITS) and become the
 * ``effectiveScale`` (unit factor x drawing scale) the page computes once.
 * The canvas labels, the annotation list, the Summary tab and every export
 * read real-world values through the helpers here, so the same distance
 * cannot read 0.05 m on the canvas and 54.85 m in the list.
 *
 * Storage convention for ``measurement_value``: the measuring tools persist
 * raw drawing units (so a later scale change re-labels them); annotations
 * made from a DXF entity and count markers already hold real values.
 */

import type { DwgAnnotation } from '../api';
import type { LayerQuantity } from './auto-quantify';
import { type CalibrationUnit, toMeters } from './calibration';

/** Annotation types whose ``measurement_value`` is stored in raw drawing units. */
const RAW_MEASURED_TYPES: ReadonlySet<DwgAnnotation['type']> = new Set([
  'distance',
  'area',
  'polyline',
  'line',
  'circle',
]);

export interface CalibrationScale {
  unitsPerPixel: number;
  unit: CalibrationUnit;
}

type MeasuredAnnotation = Pick<DwgAnnotation, 'type' | 'measurement_value' | 'measurement_unit'>;

/** Whether a measurement unit label is areal (m², ft², m2). */
export function isAreaUnit(unit: string | null | undefined): boolean {
  const u = (unit ?? '').trim();
  return u === 'm2' || u.includes('²');
}

/** Scale a raw drawing-unit value: linear x scale, areal x scale². */
export function scaleRawMeasurement(
  value: number,
  unit: string | null | undefined,
  scale: number,
): number {
  if (!Number.isFinite(scale) || scale <= 0 || scale === 1) return value;
  return isAreaUnit(unit) ? value * scale * scale : value * scale;
}

/**
 * Real-world value of one annotation in metres / m² / nr, or ``null`` when it
 * carries no number. A two-point calibration, when present, replaces the
 * preset scale exactly as it does on the canvas.
 */
export function annotationRealValue(
  ann: MeasuredAnnotation,
  effectiveScale: number,
  calibration?: CalibrationScale | null,
): number | null {
  const raw = ann.measurement_value;
  if (raw == null || !Number.isFinite(raw)) return null;
  if (!RAW_MEASURED_TYPES.has(ann.type)) return raw;
  const area = isAreaUnit(ann.measurement_unit);
  if (calibration && calibration.unitsPerPixel > 0) {
    const linearMetres = toMeters(calibration.unitsPerPixel, calibration.unit);
    return area ? raw * linearMetres * linearMetres : raw * linearMetres;
  }
  return scaleRawMeasurement(raw, ann.measurement_unit, effectiveScale);
}

export interface AnnotationTotals {
  /** Σ manual areas (m²). */
  area: number;
  /** Σ manual lengths: distances, polylines, lines (m). */
  length: number;
  /** Number of count markers. */
  count: number;
}

/** Totals of the user's manual measurements, in real-world units. */
export function annotationTotals(
  annotations: readonly MeasuredAnnotation[],
  effectiveScale: number,
  calibration?: CalibrationScale | null,
): AnnotationTotals {
  let area = 0;
  let length = 0;
  let count = 0;
  for (const ann of annotations) {
    if (ann.type === 'count') {
      count += ann.measurement_value ?? 1;
      continue;
    }
    if (!RAW_MEASURED_TYPES.has(ann.type)) continue;
    const v = annotationRealValue(ann, effectiveScale, calibration);
    if (v == null) continue;
    if (isAreaUnit(ann.measurement_unit)) area += v;
    else length += v;
  }
  return { area, length, count };
}

export interface QuantifyTotals {
  area: number;
  perimeter: number;
  length: number;
  /** Entities across all layers. */
  count: number;
}

/** Grand totals of the per-layer auto-quantify rows. The Summary KPIs, the
 *  CSV, the PDF and the XLSX all print this, so they cannot disagree. */
export function quantifyTotals(rows: readonly LayerQuantity[]): QuantifyTotals {
  let area = 0;
  let perimeter = 0;
  let length = 0;
  let count = 0;
  for (const row of rows) {
    area += row.area;
    perimeter += row.perimeter;
    length += row.length;
    count += row.count;
  }
  const round = (n: number) => Math.round(n * 1000) / 1000;
  return { area: round(area), perimeter: round(perimeter), length: round(length), count };
}
