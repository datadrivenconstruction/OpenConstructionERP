/**
 * Unit tests for the metric <-> imperial conversion helpers.
 *
 * Pure functions, no DOM. Covers length, area and volume in both
 * directions, the superscript area / volume variants used by the takeoff
 * layer ("m2" / "m" forms), the metric-display normalisation, and the
 * unknown-unit pass-through.
 */

import { describe, it, expect } from 'vitest';
import {
  convertBetween,
  convertUnit,
  getDisplayUnit,
  isMetricUnit,
  toDisplayQuantity,
  displayUnitFor,
  fromDisplayQuantity,
  conversionFactorFor,
  toDisplayRate,
  fromDisplayRate,
} from './unitConversion';
// The live unit picker. Imported so this file measures what the product
// actually offers as a storable unit rather than a copy of it that drifts.
import { UNITS } from '@/features/boq/boqHelpers';

describe('convertUnit - metric to imperial', () => {
  it('converts length m -> ft', () => {
    const r = convertUnit(10, 'm', 'imperial');
    expect(r.value).toBeCloseTo(32.808399, 5);
    expect(r.unit).toBe('ft');
    expect(r.displayUnit).toBe('ft');
  });

  it('converts area m2 -> ft2', () => {
    const r = convertUnit(10, 'm2', 'imperial');
    expect(r.value).toBeCloseTo(107.639, 3);
    expect(r.unit).toBe('ft2');
    expect(r.displayUnit).toBe('sq ft');
  });

  it('converts volume m3 -> ft3', () => {
    const r = convertUnit(10, 'm3', 'imperial');
    expect(r.value).toBeCloseTo(353.147, 3);
    expect(r.unit).toBe('ft3');
    expect(r.displayUnit).toBe('cu ft');
  });

  it('converts the superscript area unit m² -> ft²', () => {
    const r = convertUnit(10, 'm²', 'imperial');
    expect(r.value).toBeCloseTo(107.639, 3);
    expect(r.unit).toBe('ft2');
    // Superscript source keeps the superscript display style.
    expect(r.displayUnit).toBe('ft²');
  });

  it('converts the superscript volume unit m³ -> ft³', () => {
    const r = convertUnit(10, 'm³', 'imperial');
    expect(r.value).toBeCloseTo(353.147, 3);
    expect(r.unit).toBe('ft3');
    expect(r.displayUnit).toBe('ft³');
  });

  it('leaves a countable / unmapped unit unchanged', () => {
    const r = convertUnit(7, 'pcs', 'imperial');
    expect(r.value).toBe(7);
    expect(r.displayUnit).toBe('pcs');
  });
});

describe('convertUnit - imperial to metric', () => {
  it('converts length ft -> m', () => {
    const r = convertUnit(32.808399, 'ft', 'metric');
    expect(r.value).toBeCloseTo(10, 4);
    expect(r.unit).toBe('m');
  });

  it('converts area ft2 -> m2', () => {
    const r = convertUnit(107.639, 'ft2', 'metric');
    expect(r.value).toBeCloseTo(10, 3);
    expect(r.unit).toBe('m2');
  });

  it('converts volume ft3 -> m3', () => {
    const r = convertUnit(353.147, 'ft3', 'metric');
    expect(r.value).toBeCloseTo(10, 3);
    expect(r.unit).toBe('m3');
  });
});

describe('convertUnit - round-trip', () => {
  it('m -> ft -> m is identity within tolerance', () => {
    const ft = convertUnit(12.34, 'm', 'imperial');
    const back = convertUnit(ft.value, 'ft', 'metric');
    expect(back.value).toBeCloseTo(12.34, 4);
  });
});

describe('getDisplayUnit', () => {
  it('normalises ascii metric area / volume to superscripts', () => {
    expect(getDisplayUnit('m2')).toBe('m²');
    expect(getDisplayUnit('m3')).toBe('m³');
  });

  it('keeps already-superscript metric units as-is', () => {
    expect(getDisplayUnit('m²')).toBe('m²');
    expect(getDisplayUnit('m³')).toBe('m³');
  });

  it('falls back to the raw code for unknown units', () => {
    expect(getDisplayUnit('pcs')).toBe('pcs');
    expect(getDisplayUnit('')).toBe('');
  });
});

describe('isMetricUnit', () => {
  it('recognises metric units including superscript variants', () => {
    expect(isMetricUnit('m')).toBe(true);
    expect(isMetricUnit('m2')).toBe(true);
    expect(isMetricUnit('m²')).toBe(true);
    expect(isMetricUnit('m³')).toBe(true);
  });

  it('recognises imperial units', () => {
    expect(isMetricUnit('ft')).toBe(false);
    expect(isMetricUnit('ft2')).toBe(false);
  });

  it('returns null for unknown units', () => {
    expect(isMetricUnit('pcs')).toBeNull();
    expect(isMetricUnit('lsum')).toBeNull();
  });
});

describe('toDisplayQuantity', () => {
  it('passes the value through untouched for metric, only tidying the label', () => {
    const r = toDisplayQuantity(12.5, 'm2', 'metric');
    expect(r.value).toBe(12.5);
    expect(r.unit).toBe('m²');
  });

  it('keeps superscript metric labels as-is for metric', () => {
    expect(toDisplayQuantity(3, 'm³', 'metric')).toEqual({ value: 3, unit: 'm³' });
  });

  it('scales + relabels area for imperial', () => {
    const r = toDisplayQuantity(10, 'm²', 'imperial');
    expect(r.value).toBeCloseTo(107.639, 3);
    expect(r.unit).toBe('ft²');
  });

  it('scales + relabels length and weight for imperial', () => {
    expect(toDisplayQuantity(1, 'm', 'imperial').unit).toBe('ft');
    expect(toDisplayQuantity(1, 'm', 'imperial').value).toBeCloseTo(3.2808399, 5);
    expect(toDisplayQuantity(1, 'kg', 'imperial').unit).toBe('lb');
    expect(toDisplayQuantity(1, 'kg', 'imperial').value).toBeCloseTo(2.20462, 4);
  });

  it('leaves countable / lump units unchanged in both systems', () => {
    expect(toDisplayQuantity(7, 'pcs', 'imperial')).toEqual({ value: 7, unit: 'pcs' });
    expect(toDisplayQuantity(7, 'lsum', 'metric')).toEqual({ value: 7, unit: 'lsum' });
  });
});

describe('displayUnitFor', () => {
  it('returns the metric display label for metric', () => {
    expect(displayUnitFor('m2', 'metric')).toBe('m²');
    expect(displayUnitFor('m', 'metric')).toBe('m');
  });

  it('returns the imperial label for imperial', () => {
    expect(displayUnitFor('m²', 'imperial')).toBe('ft²');
    expect(displayUnitFor('m', 'imperial')).toBe('ft');
    expect(displayUnitFor('kg', 'imperial')).toBe('lb');
  });

  it('passes unmapped units through', () => {
    expect(displayUnitFor('pcs', 'imperial')).toBe('pcs');
  });
});

describe('fromDisplayQuantity (editable-cell reverse)', () => {
  it('is the identity for metric', () => {
    expect(fromDisplayQuantity(215.28, 'm²', 'metric')).toBe(215.28);
  });

  it('reverses an imperial value back to metric storage', () => {
    // 20 m² shown as ft², typed back, must store ~20 m² again.
    const shown = toDisplayQuantity(20, 'm²', 'imperial');
    expect(fromDisplayQuantity(shown.value, 'm²', 'imperial')).toBeCloseTo(20, 6);
  });

  it('reverses length and weight', () => {
    expect(fromDisplayQuantity(3.2808399, 'm', 'imperial')).toBeCloseTo(1, 6);
    expect(fromDisplayQuantity(2.20462, 'kg', 'imperial')).toBeCloseTo(1, 5);
  });

  it('passes unmapped units through unchanged', () => {
    expect(fromDisplayQuantity(7, 'pcs', 'imperial')).toBe(7);
  });
});

describe('conversionFactorFor', () => {
  it('is 1 for metric regardless of unit', () => {
    expect(conversionFactorFor('m', 'metric')).toBe(1);
    expect(conversionFactorFor('m²', 'metric')).toBe(1);
    expect(conversionFactorFor('pcs', 'metric')).toBe(1);
  });

  it('returns the metric->imperial scale for imperial', () => {
    expect(conversionFactorFor('m', 'imperial')).toBeCloseTo(3.2808399, 6);
    expect(conversionFactorFor('m²', 'imperial')).toBeCloseTo(10.7639, 4);
  });

  it('is 1 for unmapped units so callers can divide unconditionally', () => {
    expect(conversionFactorFor('pcs', 'imperial')).toBe(1);
    expect(conversionFactorFor('lsum', 'imperial')).toBe(1);
  });
});

describe('toDisplayRate / fromDisplayRate (reciprocal rate)', () => {
  it('is the identity for metric', () => {
    expect(toDisplayRate(50, 'm', 'metric')).toBe(50);
    expect(fromDisplayRate(50, 'm', 'metric')).toBe(50);
  });

  it('restates a per-metre rate against feet (50/m -> 15.24/ft)', () => {
    expect(toDisplayRate(50, 'm', 'imperial')).toBeCloseTo(15.24, 2);
  });

  it('reverses a typed imperial rate back to metric storage', () => {
    const shown = toDisplayRate(50, 'm', 'imperial');
    expect(fromDisplayRate(shown, 'm', 'imperial')).toBeCloseTo(50, 6);
  });

  it('passes unmapped units through unchanged', () => {
    expect(toDisplayRate(50, 'pcs', 'imperial')).toBe(50);
    expect(fromDisplayRate(50, 'pcs', 'imperial')).toBe(50);
  });

  it('keeps the line total invariant: displayed qty * displayed rate == metric qty * metric rate', () => {
    // A line: 2.31 m at 50 currency / m = 115.50 total (canonical).
    const qtyMetric = 2.31;
    const rateMetric = 50;
    const totalMetric = qtyMetric * rateMetric;
    const qtyShown = toDisplayQuantity(qtyMetric, 'm', 'imperial').value; // ~7.58 ft
    const rateShown = toDisplayRate(rateMetric, 'm', 'imperial'); // ~15.24 / ft
    // The reciprocal pair reconciles to the same (invariant) total, unlike a
    // converted qty against a raw rate (7.58 * 50 = 379, the bug this fixes).
    expect(qtyShown * rateShown).toBeCloseTo(totalMetric, 6);
  });
});

describe('extended unit coverage (#285)', () => {
  it('converts small areas to square inches', () => {
    expect(toDisplayQuantity(1, 'cm2', 'imperial').unit).toBe('sq in');
    expect(toDisplayQuantity(1, 'cm2', 'imperial').value).toBeCloseTo(0.15500031, 6);
    expect(toDisplayQuantity(1, 'mm²', 'imperial').unit).toBe('in²');
  });

  it('converts hectares to acres and litres to gallons', () => {
    expect(toDisplayQuantity(1, 'ha', 'imperial').unit).toBe('ac');
    expect(toDisplayQuantity(1, 'ha', 'imperial').value).toBeCloseTo(2.4710538, 5);
    expect(toDisplayQuantity(1, 'l', 'imperial').unit).toBe('gal');
    expect(toDisplayQuantity(1, 'l', 'imperial').value).toBeCloseTo(0.264172052, 6);
  });

  it('round-trips an extended unit back to metric storage', () => {
    const shown = toDisplayQuantity(3.5, 'ha', 'imperial');
    expect(fromDisplayQuantity(shown.value, 'ha', 'imperial')).toBeCloseTo(3.5, 6);
  });
});

describe('convertBetween (unit-to-unit within a dimension, #319 / #320)', () => {
  it('converts metre cubed into US trade volume units', () => {
    expect(convertBetween(10, 'm3', 'cy')).toBeCloseTo(13.0795, 4);
    expect(convertBetween(1, 'm3', 'ft3')).toBeCloseTo(35.3147, 4);
    expect(convertBetween(1, 'm3', 'bdft')).toBeCloseTo(423.776, 3);
    expect(convertBetween(1, 'm3', 'yd3')).toBeCloseTo(1.30795, 5);
  });

  it('converts metre squared into roofing squares and square feet', () => {
    expect(convertBetween(1, 'm2', 'sq')).toBeCloseTo(0.107639, 6);
    expect(convertBetween(1, 'm2', 'ft2')).toBeCloseTo(10.7639, 4);
  });

  it('folds superscript source codes to the same factor', () => {
    expect(convertBetween(2, 'm³', 'cy')).toBeCloseTo(2.6159, 4);
    expect(convertBetween(3, 'm²', 'sq')).toBeCloseTo(0.322917, 6);
  });

  it('passes the value through for the same unit both sides', () => {
    expect(convertBetween(5, 'm3', 'm3')).toBe(5);
  });

  it('refuses cross-dimension and unknown-unit conversions with null', () => {
    expect(convertBetween(1, 'm3', 'm2')).toBeNull();
    expect(convertBetween(1, 'm2', 'm')).toBeNull();
    expect(convertBetween(1, 'm3', 'lsum')).toBeNull();
    expect(convertBetween(1, 'kg', 'cy')).toBeNull();
  });

  it('passes the value through when a unit is missing', () => {
    expect(convertBetween(7, null, 'm3')).toBe(7);
    expect(convertBetween(7, 'm3', undefined)).toBe(7);
    expect(convertBetween(7, 'm3', '')).toBe(7);
  });

  it('agrees with the metric->imperial display factor for m3 -> ft3', () => {
    const between = convertBetween(4, 'm3', 'ft3');
    const display = convertUnit(4, 'm3', 'imperial').value;
    expect(between).toBeCloseTo(display, 6);
  });
});

/* ── Picker population: an imperial unit must never be scaled ─────────── */

/**
 * `toDisplayQuantity` calls its parameter `metricUnit`, but the unit field is
 * not restricted to metric. The picker (`BASE_UNITS` in
 * features/boq/boqHelpers.ts) offers imperial and US trade tokens as storable
 * values, so a US estimator's position can reach the converter already
 * expressed in cubic yards. Nothing scales it today because the lookup is
 * keyed on metric tokens only - the imperial token matches nothing and falls
 * through. This block pins that, because the property currently holds by the
 * shape of one table and would break silently if a token were added to the
 * wrong side of it: the quantity would then be multiplied a second time and
 * the printed line would carry a wrong number at the right total.
 *
 * The imperial list is written out rather than derived from the converter's
 * own tables on purpose. A gate that asked the converter which units are
 * imperial would agree with the converter by construction and go green in
 * exactly the case it exists to catch.
 */
const IMPERIAL_PICKER_TOKENS = [
  'in', 'ft', 'yd', 'mi',
  'sqft', 'sqyd', 'acre', 'sq',
  'cuft', 'cuyd', 'gal', 'oz', 'lb', 'cwt', 'ton',
  'cy', 'lf', 'msf', 'mbf', 'bdft',
] as const;

/**
 * The picker tokens that MUST scale under `imperial` - the metric ones the
 * converter knows. Asserted as an exact set so the check fails in both
 * directions: an imperial token wrongly given a metric mapping appears here
 * as an unexpected member, and a metric mapping quietly dropped appears as a
 * missing one.
 */
const EXPECTED_SCALING_TOKENS = [
  'mm', 'cm', 'm', 'km', 'lm',
  'mm2', 'cm2', 'dm2', 'm2', 'ha',
  'm3', 'l',
  'kg', 't',
];

describe('unit picker population (imperial storage is never re-converted)', () => {
  it('offers a population big enough for the verdict to mean anything', () => {
    // Measured 2026-09-07: 96 tokens in the picker, 20 of them imperial / US
    // trade units and 14 metric ones the converter scales. Floors, not exact
    // counts, so adding a countable or a locale token does not fail the file.
    expect(UNITS.length).toBeGreaterThanOrEqual(90);
    expect(IMPERIAL_PICKER_TOKENS.length).toBe(20);
  });

  it('still offers every imperial token this block claims to cover', () => {
    // Guards the list above against drift: a token renamed or dropped from
    // the picker must not leave a silently empty assertion behind.
    const missing = IMPERIAL_PICKER_TOKENS.filter((u) => !UNITS.includes(u));
    expect(missing).toEqual([]);
  });

  it('passes an imperial-stored quantity through unscaled in imperial mode', () => {
    for (const unit of IMPERIAL_PICKER_TOKENS) {
      expect(toDisplayQuantity(7.5, unit, 'imperial').value).toBe(7.5);
      expect(conversionFactorFor(unit, 'imperial')).toBe(1);
      // The paired rate must not move either, or the line stops reconciling.
      expect(toDisplayRate(250, unit, 'imperial')).toBe(250);
    }
  });

  it('scales exactly the metric picker tokens and no others', () => {
    const scaling = UNITS.filter((u) => conversionFactorFor(u, 'imperial') !== 1);
    expect([...scaling].sort()).toEqual([...EXPECTED_SCALING_TOKENS].sort());
  });

  it('still converts metric quantities, so the check above is not vacuous', () => {
    // The other direction: if the converter stopped converting anything, every
    // assertion above would pass. One known scaling case holds it honest.
    expect(toDisplayQuantity(10, 'm2', 'imperial').value).toBeCloseTo(107.639, 3);
    expect(conversionFactorFor('m2', 'imperial')).toBeGreaterThan(1);
  });
});
