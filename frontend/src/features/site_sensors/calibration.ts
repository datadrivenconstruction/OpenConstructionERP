// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Calibration table helpers: typed rows to API points, and the warnings the
 * sensor checks raise (fewer than 4 cubes, R² under 0.9).
 */
import type { CalibrationPoint } from './api';

export interface CalibrationRow {
  index: string;
  mpa: string;
}

export const MIN_CALIBRATION_POINTS = 4;
export const MIN_CALIBRATION_R2 = 0.9;

/** Rows with a positive index and strength, as API points; blank or invalid rows are dropped. */
export function parseCalibrationRows(rows: readonly CalibrationRow[]): CalibrationPoint[] {
  return rows
    .map((r) => ({ index: Number(r.index), mpa: Number(r.mpa) }))
    .filter((r) => Number.isFinite(r.index) && r.index > 0 && Number.isFinite(r.mpa) && r.mpa > 0)
    .map((r) => ({ maturity_index: r.index, strength_mpa: String(r.mpa) }));
}

/** Which calibration warnings apply; none for an empty table (the curve check covers that). */
export function calibrationWarnings(points: number, r2: number | null): ('few_points' | 'low_r2')[] {
  if (points === 0) return [];
  const out: ('few_points' | 'low_r2')[] = [];
  if (points < MIN_CALIBRATION_POINTS) out.push('few_points');
  if (r2 !== null && r2 < MIN_CALIBRATION_R2) out.push('low_r2');
  return out;
}
