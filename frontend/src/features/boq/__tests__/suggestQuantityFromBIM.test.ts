// @ts-nocheck
/**
 * Unit tests for suggestQuantityFromBIM — the BIM→BOQ quantity helper.
 *
 * Covers:
 *   - Each unit-to-param mapping (m³, m², m, kg, pcs, lsum)
 *   - Multi-element sums
 *   - Missing-param fallbacks
 *   - Unit-string normalization (m3 vs m³, Stk vs шт vs pcs)
 *   - Density-fallback for kg
 *   - Zero-element edge case
 *   - Properties-fallback when quantities is empty
 *   - Confidence grading (high / medium / low)
 *   - Badge formatter
 */

import { describe, it, expect } from 'vitest';
import {
  suggestQuantityFromBIM,
  normalizeUnit,
  formatSuggestionBadge,
} from '../suggestQuantityFromBIM';
import type { BIMElementData } from '@/shared/ui/BIMViewer/ElementManager';

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

/** Build a minimal BIMElementData with whatever quantities/properties we
 *  want to inject.  Required fields (`id`, `name`, `element_type`, `discipline`)
 *  are stubbed with placeholders. */
function el(overrides: Partial<BIMElementData> = {}): BIMElementData {
  return {
    id: overrides.id ?? 'el-' + Math.random().toString(36).slice(2, 8),
    name: 'Test Element',
    element_type: 'Walls',
    discipline: 'structural',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// normalizeUnit
// ---------------------------------------------------------------------------

describe('normalizeUnit', () => {
  it('canonicalizes volume aliases', () => {
    expect(normalizeUnit('m³')).toBe('m3');
    expect(normalizeUnit('m3')).toBe('m3');
    expect(normalizeUnit('M3')).toBe('m3');
    expect(normalizeUnit(' cbm ')).toBe('m3');
    expect(normalizeUnit('m^3')).toBe('m3');
  });

  it('canonicalizes area aliases', () => {
    expect(normalizeUnit('m²')).toBe('m2');
    expect(normalizeUnit('m2')).toBe('m2');
    expect(normalizeUnit('SQM')).toBe('m2');
  });

  it('canonicalizes length, mass, count and lsum', () => {
    expect(normalizeUnit('m')).toBe('m');
    expect(normalizeUnit('lm')).toBe('m');
    expect(normalizeUnit('kg')).toBe('kg');
    expect(normalizeUnit('pcs')).toBe('pcs');
    expect(normalizeUnit('Stk')).toBe('pcs');
    expect(normalizeUnit('Stk.')).toBe('pcs');
    expect(normalizeUnit('шт')).toBe('pcs');
    expect(normalizeUnit('lsum')).toBe('lsum');
    expect(normalizeUnit('LS')).toBe('lsum');
  });

  it('returns empty for unknown / null', () => {
    expect(normalizeUnit(null)).toBe('');
    expect(normalizeUnit(undefined)).toBe('');
    expect(normalizeUnit('')).toBe('');
    expect(normalizeUnit('mol')).toBe('');
  });
});

// ---------------------------------------------------------------------------
// suggestQuantityFromBIM
// ---------------------------------------------------------------------------

describe('suggestQuantityFromBIM — volume (m³)', () => {
  it('reads volume_m3 from quantities (single element)', () => {
    const e = el({ quantities: { volume_m3: 9.0, area_m2: 37.5, length_m: 12.5 } });
    const r = suggestQuantityFromBIM([e], 'm³');
    expect(r.value).toBeCloseTo(9.0);
    expect(r.source).toBe('sum_volume');
    expect(r.confidence).toBe('high');
    expect(r.matchedKey).toBe('quantities.volume_m3');
    expect(r.inferredUnit).toBe('m³');
    expect(r.contributingElements).toBe(1);
  });

  it('sums volume across multiple elements', () => {
    const a = el({ quantities: { volume_m3: 9.0 } });
    const b = el({ quantities: { volume_m3: 4.5 } });
    const c = el({ quantities: { volume_m3: 3.9 } });
    const r = suggestQuantityFromBIM([a, b, c], 'm3');
    expect(r.value).toBeCloseTo(17.4);
    expect(r.source).toBe('sum_volume');
    expect(r.confidence).toBe('high');
    expect(r.contributingElements).toBe(3);
    expect(r.totalElements).toBe(3);
  });

  it('falls back to NetVolume property when quantities.volume is absent', () => {
    const e = el({ properties: { NetVolume: 12.0, GrossVolume: 14.0 } });
    const r = suggestQuantityFromBIM([e], 'm³');
    expect(r.value).toBeCloseTo(12.0);
    expect(r.matchedKey).toBe('properties.NetVolume');
  });

  it('grades confidence as medium when only some elements contribute', () => {
    const a = el({ quantities: { volume_m3: 5.0 } });
    const b = el({ /* no quantities */ });
    const r = suggestQuantityFromBIM([a, b], 'm³');
    expect(r.value).toBeCloseTo(5.0);
    expect(r.confidence).toBe('medium');
    expect(r.contributingElements).toBe(1);
    expect(r.totalElements).toBe(2);
  });

  it('returns zero with low confidence when no volume field present anywhere', () => {
    const e = el({ quantities: { area_m2: 10.0 } });
    const r = suggestQuantityFromBIM([e], 'm³');
    expect(r.value).toBe(0);
    expect(r.confidence).toBe('low');
    expect(r.source).toBe('sum_volume');
  });
});

describe('suggestQuantityFromBIM — area (m²)', () => {
  it('reads area_m2 from quantities', () => {
    const e = el({ quantities: { area_m2: 37.5 } });
    const r = suggestQuantityFromBIM([e], 'm²');
    expect(r.value).toBeCloseTo(37.5);
    expect(r.source).toBe('sum_area');
  });

  it('falls back to NetArea property', () => {
    const e = el({ properties: { NetArea: 25.0, GrossArea: 30.0 } });
    const r = suggestQuantityFromBIM([e], 'm2');
    expect(r.value).toBeCloseTo(25.0);
    expect(r.matchedKey).toBe('properties.NetArea');
  });

  it('falls back further to NetSideArea (e.g. Walls)', () => {
    const e = el({ properties: { NetSideArea: 18.5 } });
    const r = suggestQuantityFromBIM([e], 'm²');
    expect(r.value).toBeCloseTo(18.5);
    expect(r.matchedKey).toBe('properties.NetSideArea');
  });

  it('sums area across two elements', () => {
    const a = el({ quantities: { area_m2: 10.0 } });
    const b = el({ quantities: { area_m2: 12.5 } });
    const r = suggestQuantityFromBIM([a, b], 'm²');
    expect(r.value).toBeCloseTo(22.5);
    expect(r.contributingElements).toBe(2);
  });
});

describe('suggestQuantityFromBIM — length (m)', () => {
  it('reads length_m from quantities', () => {
    const e = el({ quantities: { length_m: 12.5 } });
    const r = suggestQuantityFromBIM([e], 'm');
    expect(r.value).toBeCloseTo(12.5);
    expect(r.source).toBe('sum_length');
  });

  it('falls back to Length property when quantities absent', () => {
    const e = el({ properties: { Length: 8.0 } });
    const r = suggestQuantityFromBIM([e], 'm');
    expect(r.value).toBeCloseTo(8.0);
    expect(r.matchedKey).toBe('properties.Length');
  });

  it('falls back to Height when no Length is present', () => {
    const e = el({ properties: { Height: 3.0 } });
    const r = suggestQuantityFromBIM([e], 'm');
    expect(r.value).toBeCloseTo(3.0);
    expect(r.matchedKey).toBe('properties.Height');
  });
});

describe('suggestQuantityFromBIM — mass (kg)', () => {
  it('reads NetWeight directly when present', () => {
    const e = el({ properties: { NetWeight: 250.0 } });
    const r = suggestQuantityFromBIM([e], 'kg');
    expect(r.value).toBeCloseTo(250.0);
    expect(r.source).toBe('sum_mass');
    expect(r.confidence).toBe('high');
  });

  it('computes from volume × density when weight is absent', () => {
    const e = el({
      quantities: { volume_m3: 1.0 },
      properties: { Density: 2400 }, // concrete
    });
    const r = suggestQuantityFromBIM([e], 'kg');
    expect(r.value).toBeCloseTo(2400.0);
    expect(r.source).toBe('computed_mass_from_density');
    expect(r.confidence).toBe('low');
  });

  it('returns zero low-confidence when neither weight nor density+volume is known', () => {
    const e = el({ quantities: { area_m2: 5.0 } });
    const r = suggestQuantityFromBIM([e], 'kg');
    expect(r.value).toBe(0);
    expect(r.confidence).toBe('low');
  });
});

describe('suggestQuantityFromBIM — count (pcs / Stk / шт)', () => {
  it('counts elements for pcs', () => {
    const r = suggestQuantityFromBIM([el(), el(), el()], 'pcs');
    expect(r.value).toBe(3);
    expect(r.source).toBe('count');
    expect(r.confidence).toBe('high');
  });

  it('treats Stk as a count unit', () => {
    const r = suggestQuantityFromBIM([el(), el()], 'Stk');
    expect(r.value).toBe(2);
    expect(r.source).toBe('count');
  });

  it('treats шт (Russian) as a count unit', () => {
    const r = suggestQuantityFromBIM([el()], 'шт');
    expect(r.value).toBe(1);
    expect(r.source).toBe('count');
  });
});

describe('suggestQuantityFromBIM — lsum', () => {
  it('always returns 1 for lump sum', () => {
    const r = suggestQuantityFromBIM([el(), el(), el()], 'lsum');
    expect(r.value).toBe(1);
    expect(r.source).toBe('lsum');
    expect(r.confidence).toBe('high');
  });
});

describe('suggestQuantityFromBIM — edge cases', () => {
  it('handles zero elements', () => {
    const r = suggestQuantityFromBIM([], 'm³');
    expect(r.value).toBe(0);
    expect(r.source).toBe('no_elements');
    expect(r.confidence).toBe('low');
    expect(r.totalElements).toBe(0);
  });

  it('falls back to volume → area → length → count when unit is empty / unknown', () => {
    const a = el({ quantities: { volume_m3: 7.5, area_m2: 30.0 } });
    const r = suggestQuantityFromBIM([a], '');
    expect(r.source).toBe('sum_volume');
    expect(r.value).toBeCloseTo(7.5);
    expect(r.confidence).toBe('low'); // unknown unit → always low
  });

  it('falls back to area when no volume is present and unit is unknown', () => {
    const a = el({ quantities: { area_m2: 30.0 } });
    const r = suggestQuantityFromBIM([a], '');
    expect(r.source).toBe('sum_area');
    expect(r.value).toBeCloseTo(30.0);
  });

  it('falls back to count when nothing else is present and unit is unknown', () => {
    const r = suggestQuantityFromBIM([el(), el()], 'mol' /* unknown unit */);
    expect(r.source).toBe('unit_unknown');
    expect(r.value).toBe(2);
  });

  it('coerces stringified numbers ("9.5") to numeric', () => {
    const e = el({ properties: { NetVolume: '9.5' as unknown as number } });
    const r = suggestQuantityFromBIM([e], 'm³');
    expect(r.value).toBeCloseTo(9.5);
  });

  it('matches property keys case-insensitively', () => {
    const e = el({ properties: { netvolume: 4.2 } });
    const r = suggestQuantityFromBIM([e], 'm³');
    expect(r.value).toBeCloseTo(4.2);
  });

  it('ignores NaN / non-finite property values', () => {
    const e = el({ quantities: { volume_m3: Number.NaN as number } });
    const r = suggestQuantityFromBIM([e], 'm³');
    expect(r.value).toBe(0);
    expect(r.contributingElements).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// formatSuggestionBadge
// ---------------------------------------------------------------------------

describe('formatSuggestionBadge', () => {
  it('formats sum_volume with element count', () => {
    const a = el({ quantities: { volume_m3: 9.0 } });
    const b = el({ quantities: { volume_m3: 8.4 } });
    const r = suggestQuantityFromBIM([a, b], 'm³');
    const label = formatSuggestionBadge(r);
    expect(label).toContain('Σ volume');
    expect(label).toContain('17.4');
    expect(label).toContain('m³');
    expect(label).toContain('2/2');
  });

  it('formats count without element count', () => {
    const r = suggestQuantityFromBIM([el(), el(), el()], 'pcs');
    expect(formatSuggestionBadge(r)).toBe('count = 3 pcs');
  });

  it('formats lsum', () => {
    const r = suggestQuantityFromBIM([el()], 'lsum');
    expect(formatSuggestionBadge(r)).toBe('lump sum = 1');
  });

  it('formats computed mass with the density caveat', () => {
    const e = el({
      quantities: { volume_m3: 1.0 },
      properties: { Density: 7850 }, // steel
    });
    const r = suggestQuantityFromBIM([e], 'kg');
    expect(formatSuggestionBadge(r)).toContain('volume × density');
  });

  it('formats no_elements case', () => {
    const r = suggestQuantityFromBIM([], 'm³');
    expect(formatSuggestionBadge(r)).toBe('no elements selected');
  });
});
