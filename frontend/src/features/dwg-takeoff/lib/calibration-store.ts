/**
 * LocalStorage persistence for DWG calibration state.
 *
 * Keyed by ``dwg-cal:{projectId}:{filename}:{layout}`` so that a single
 * drawing file with multiple paper-space layouts keeps an independent
 * scale per layout (common case: Model space is unitless, "A-100" has
 * title block scale 1:50, "A-101" has 1:100). Falls back to a plain
 * object with minimal validation on read so corrupted / downgrade-era
 * entries don't poison the viewer — we just return ``null`` and the
 * user re-calibrates.
 */

import type { CalibrationState, CalibrationUnit } from './calibration';

/** Key prefix. Exported so tests and devtools can vacuum old entries
 *  without sprinkling magic strings around the codebase. */
export const CALIBRATION_KEY_PREFIX = 'dwg-cal';

/** Build the canonical localStorage key from its three parts. Layout
 *  defaults to ``"__default__"`` when the drawing has a single layout,
 *  so the ``:layout`` segment is always present and key parsing stays
 *  trivial. */
export function calibrationKey(
  projectId: string,
  filename: string,
  layout: string | null | undefined,
): string {
  const l = layout && layout.length > 0 ? layout : '__default__';
  return `${CALIBRATION_KEY_PREFIX}:${projectId}:${filename}:${l}`;
}

const VALID_UNITS: ReadonlySet<CalibrationUnit> = new Set([
  'm',
  'mm',
  'ft',
  'in',
]);

/** Load a calibration by key. Returns ``null`` when missing, malformed,
 *  or when ``localStorage`` is unavailable (SSR / privacy-mode). */
export function loadCalibration(key: string): CalibrationState | null {
  try {
    if (typeof localStorage === 'undefined') return null;
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const obj = parsed as Record<string, unknown>;
    const upp = obj.unitsPerPixel;
    const unit = obj.unit;
    const ts = obj.calibratedAt;
    if (
      typeof upp !== 'number' ||
      !Number.isFinite(upp) ||
      upp <= 0 ||
      typeof unit !== 'string' ||
      !VALID_UNITS.has(unit as CalibrationUnit) ||
      typeof ts !== 'number'
    ) {
      return null;
    }
    const state: CalibrationState = {
      unitsPerPixel: upp,
      unit: unit as CalibrationUnit,
      calibratedAt: ts,
    };
    if (Array.isArray(obj.pointA) && obj.pointA.length === 2) {
      const [x, y] = obj.pointA as unknown[];
      if (typeof x === 'number' && typeof y === 'number') {
        state.pointA = [x, y];
      }
    }
    if (Array.isArray(obj.pointB) && obj.pointB.length === 2) {
      const [x, y] = obj.pointB as unknown[];
      if (typeof x === 'number' && typeof y === 'number') {
        state.pointB = [x, y];
      }
    }
    return state;
  } catch {
    return null;
  }
}

/** Persist a calibration. Swallows storage errors (quota exceeded,
 *  private-browsing blocks) so a failed save never crashes the UI — the
 *  user just re-calibrates next session. */
export function saveCalibration(
  key: string,
  state: CalibrationState | null,
): void {
  try {
    if (typeof localStorage === 'undefined') return;
    if (state === null) {
      localStorage.removeItem(key);
      return;
    }
    localStorage.setItem(key, JSON.stringify(state));
  } catch {
    // Ignore — localStorage is best-effort.
  }
}

/** Remove a calibration. Convenience wrapper so callers don't have to
 *  pass ``null`` to ``saveCalibration`` (which is technically the same
 *  but reads less naturally). */
export function clearCalibration(key: string): void {
  saveCalibration(key, null);
}
