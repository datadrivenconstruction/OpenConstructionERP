/**
 * Unit tests for the two-click DWG calibration math.
 *
 * Covers:
 *   - ``deriveScale``: the core pixels → real-world conversion.
 *   - Unit conversion helpers (``toMeters`` / ``fromMeters``).
 *   - Formatting (``formatWithUnit`` / ``formatAreaWithUnit``).
 *   - Edge cases: zero pixel distance, negative real length, degenerate
 *     inputs that should raise ``ZeroPixelDistanceError``.
 *   - localStorage round-trip via ``loadCalibration`` / ``saveCalibration``.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
  deriveScale,
  toMeters,
  fromMeters,
  formatWithUnit,
  formatAreaWithUnit,
  pixelDistance,
  ZeroPixelDistanceError,
  CALIBRATION_UNITS,
} from '../calibration';
import {
  calibrationKey,
  loadCalibration,
  saveCalibration,
  clearCalibration,
} from '../calibration-store';

/* ── deriveScale ─────────────────────────────────────────────────────── */

describe('deriveScale', () => {
  it('returns unitsPerPixel = realLength / pixelLength (100 px at 5 m → 0.05 m/px)', () => {
    const result = deriveScale([0, 0], [100, 0], 5, 'm');
    expect(result.unitsPerPixel).toBeCloseTo(0.05, 10);
    expect(result.unit).toBe('m');
  });

  it('handles diagonal pixel distance correctly', () => {
    // 3-4-5 triangle: hypotenuse = 5 px → 5 m real → 1 m/px.
    const result = deriveScale([0, 0], [3, 4], 5, 'm');
    expect(result.unitsPerPixel).toBeCloseTo(1, 10);
  });

  it('accepts {x, y} object points as well as tuples', () => {
    const result = deriveScale(
      { x: 0, y: 0 },
      { x: 0, y: 200 },
      10,
      'm',
    );
    expect(result.unitsPerPixel).toBeCloseTo(0.05, 10);
  });

  it('keeps the user-chosen unit on the returned scale', () => {
    const result = deriveScale([0, 0], [100, 0], 5000, 'mm');
    expect(result.unit).toBe('mm');
    expect(result.unitsPerPixel).toBeCloseTo(50, 10);
  });

  it('throws ZeroPixelDistanceError when the two points coincide', () => {
    expect(() => deriveScale([10, 10], [10, 10], 5, 'm')).toThrow(
      ZeroPixelDistanceError,
    );
  });

  it('throws ZeroPixelDistanceError on zero/negative real length', () => {
    expect(() => deriveScale([0, 0], [100, 0], 0, 'm')).toThrow(
      ZeroPixelDistanceError,
    );
    expect(() => deriveScale([0, 0], [100, 0], -5, 'm')).toThrow(
      ZeroPixelDistanceError,
    );
  });

  it('throws on non-finite inputs', () => {
    expect(() => deriveScale([0, 0], [NaN, 0], 5, 'm')).toThrow(
      ZeroPixelDistanceError,
    );
    expect(() => deriveScale([0, 0], [100, 0], Infinity, 'm')).toThrow(
      ZeroPixelDistanceError,
    );
  });
});

/* ── Unit conversion ─────────────────────────────────────────────────── */

describe('toMeters / fromMeters', () => {
  it('1000 mm == 1 m', () => {
    expect(toMeters(1000, 'mm')).toBe(1);
    expect(fromMeters(1, 'mm')).toBe(1000);
  });

  it('1 m == 1 m (identity)', () => {
    expect(toMeters(1, 'm')).toBe(1);
    expect(fromMeters(1, 'm')).toBe(1);
  });

  it('12 in == 1 ft (via metres)', () => {
    // 12 in → metres → ft should be 1 ft.
    const asMetres = toMeters(12, 'in');
    expect(fromMeters(asMetres, 'ft')).toBeCloseTo(1, 10);
  });

  it('uses exact conversions: 1 ft = 0.3048 m, 1 in = 0.0254 m', () => {
    expect(toMeters(1, 'ft')).toBeCloseTo(0.3048, 12);
    expect(toMeters(1, 'in')).toBeCloseTo(0.0254, 12);
  });

  it('round-trips through metres for all units', () => {
    for (const u of CALIBRATION_UNITS) {
      const v = 42.5;
      expect(fromMeters(toMeters(v, u), u)).toBeCloseTo(v, 10);
    }
  });
});

/* ── formatWithUnit ──────────────────────────────────────────────────── */

describe('formatWithUnit', () => {
  it('formats 100 px at 0.05 m/px as "5.00 m"', () => {
    const scale = { unitsPerPixel: 0.05, unit: 'm' as const };
    expect(formatWithUnit(100, scale)).toBe('5.00 m');
  });

  it('falls back to pixels + "(uncal)" when scale is null', () => {
    const out = formatWithUnit(42.5, null);
    expect(out).toContain('px');
    expect(out).toContain('uncal');
  });

  it('falls back to pixels + "(uncal)" when scale is undefined', () => {
    expect(formatWithUnit(10, undefined)).toMatch(/px/);
  });

  it('uses 3-decimal precision for sub-unit values', () => {
    const scale = { unitsPerPixel: 0.001, unit: 'm' as const };
    // 100 px × 0.001 = 0.1 m → "0.100 m"
    expect(formatWithUnit(100, scale)).toBe('0.100 m');
  });

  it('uses kilo-suffix for very large values', () => {
    const scale = { unitsPerPixel: 10, unit: 'm' as const };
    // 200 px × 10 = 2000 m → "2.00k m"
    expect(formatWithUnit(200, scale)).toBe('2.00k m');
  });

  it('respects the chosen unit in the label', () => {
    const scale = { unitsPerPixel: 0.5, unit: 'ft' as const };
    expect(formatWithUnit(10, scale)).toBe('5.00 ft');
  });
});

describe('formatAreaWithUnit', () => {
  it('squares the unitsPerPixel and appends a squared unit', () => {
    const scale = { unitsPerPixel: 0.5, unit: 'm' as const };
    // 100 px² × 0.25 = 25 m²
    expect(formatAreaWithUnit(100, scale)).toBe('25.00 m\u00B2');
  });

  it('falls back to "px² (uncal)" with no scale', () => {
    expect(formatAreaWithUnit(1000, null)).toContain('px');
    expect(formatAreaWithUnit(1000, null)).toContain('uncal');
  });
});

describe('pixelDistance', () => {
  it('accepts tuples and objects interchangeably', () => {
    expect(pixelDistance([0, 0], [3, 4])).toBe(5);
    expect(pixelDistance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
    expect(pixelDistance([0, 0], { x: 3, y: 4 })).toBe(5);
  });
});

/* ── localStorage round-trip ─────────────────────────────────────────── */

describe('calibration-store', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('builds a stable key from projectId + filename + layout', () => {
    const k = calibrationKey('proj-1', 'plan.dwg', 'A-100');
    expect(k).toBe('dwg-cal:proj-1:plan.dwg:A-100');
  });

  it('defaults the layout segment when layout is null/empty', () => {
    expect(calibrationKey('p', 'f.dwg', null)).toBe(
      'dwg-cal:p:f.dwg:__default__',
    );
    expect(calibrationKey('p', 'f.dwg', '')).toBe(
      'dwg-cal:p:f.dwg:__default__',
    );
  });

  it('round-trips a saved calibration', () => {
    const key = calibrationKey('p', 'plan.dwg', 'Model');
    const state = {
      unitsPerPixel: 0.05,
      unit: 'm' as const,
      calibratedAt: 1_234_567_890,
      pointA: [0, 0] as [number, number],
      pointB: [100, 0] as [number, number],
    };
    saveCalibration(key, state);
    const loaded = loadCalibration(key);
    expect(loaded).toEqual(state);
  });

  it('returns null for missing / malformed entries', () => {
    expect(loadCalibration('dwg-cal:none:none:none')).toBeNull();
    localStorage.setItem('dwg-cal:p:f:l', '{not json');
    expect(loadCalibration('dwg-cal:p:f:l')).toBeNull();
    localStorage.setItem('dwg-cal:p:f:l', JSON.stringify({ unit: 'm' }));
    expect(loadCalibration('dwg-cal:p:f:l')).toBeNull();
  });

  it('rejects corrupt unit values', () => {
    const key = 'dwg-cal:p:f:l';
    localStorage.setItem(
      key,
      JSON.stringify({
        unitsPerPixel: 1,
        unit: 'parsec',
        calibratedAt: 1,
      }),
    );
    expect(loadCalibration(key)).toBeNull();
  });

  it('clearCalibration removes the entry', () => {
    const key = calibrationKey('p', 'f.dwg', 'L');
    saveCalibration(key, {
      unitsPerPixel: 1,
      unit: 'm',
      calibratedAt: 1,
    });
    clearCalibration(key);
    expect(loadCalibration(key)).toBeNull();
  });
});
