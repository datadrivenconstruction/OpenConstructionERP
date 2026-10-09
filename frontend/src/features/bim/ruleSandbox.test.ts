// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Unit tests for the BIM Quantity Rules sandbox pure logic.
 *
 * These pin the client-side mirror of the backend rule engine plus the new
 * unit-safety, coverage and versioning helpers. The matching/quantity tests
 * intentionally echo the backend's ``test_bim_property_matcher.py`` so the two
 * engines can never silently drift apart.
 */

import { describe, expect, it } from 'vitest';

import {
  applyAdjustment,
  buildCoverageReport,
  checkUnitSafety,
  dimensionForSource,
  dimensionForUnit,
  draftConfidence,
  extractRawQuantity,
  filterCoversCategory,
  fnmatchCI,
  formulaSignature,
  propertyValueMatches,
  pushVersion,
  readVersions,
  ruleMatchesElement,
  runSandbox,
  type CoverageRule,
  type RuleFormulaFields,
  type SandboxElement,
  type SandboxRule,
} from './ruleSandbox';

/* ── fnmatch ─────────────────────────────────────────────────────────────── */

describe('fnmatchCI', () => {
  it('matches literal case-insensitively', () => {
    expect(fnmatchCI('Walls', 'walls')).toBe(true);
  });
  it('honours star and question wildcards', () => {
    expect(fnmatchCI('IfcWallStandardCase', 'IfcWall*')).toBe(true);
    expect(fnmatchCI('F90', 'F?0')).toBe(true);
    expect(fnmatchCI('F900', 'F?0')).toBe(false);
  });
  it('escapes regex-special characters in the literal portion', () => {
    expect(fnmatchCI('Wall (Ext)', 'Wall (Ext)')).toBe(true);
    expect(fnmatchCI('WallXExt', 'Wall (Ext)')).toBe(false);
  });
});

/* ── propertyValueMatches (mirror of backend matcher) ────────────────────── */

describe('propertyValueMatches', () => {
  it('does string fnmatch', () => {
    expect(propertyValueMatches('concrete_c30_37', 'concrete_*')).toBe(true);
    expect(propertyValueMatches('wood', 'steel')).toBe(false);
  });
  it('does list membership for scalar filters', () => {
    expect(propertyValueMatches(['steel', 'concrete'], 'steel')).toBe(true);
    expect(propertyValueMatches(['wood', 'drywall'], 'steel')).toBe(false);
  });
  it('does list intersection for list filters', () => {
    expect(propertyValueMatches(['steel', 'concrete'], ['steel', 'wood'])).toBe(true);
    expect(propertyValueMatches(['wood'], ['steel', 'concrete'])).toBe(false);
  });
  it('does dict recursive containment', () => {
    expect(
      propertyValueMatches({ layers: { core: 'steel' }, thick: 200 }, { layers: { core: 'steel' } }),
    ).toBe(true);
    expect(propertyValueMatches({ layers: { core: 'wood' } }, { layers: { core: 'steel' } })).toBe(
      false,
    );
  });
  it('treats expected null/undefined as must-not-be-set', () => {
    expect(propertyValueMatches(null, null)).toBe(true);
    expect(propertyValueMatches('anything', null)).toBe(false);
  });
  it('fails when actual is missing but a value was wanted', () => {
    expect(propertyValueMatches(undefined, 'steel')).toBe(false);
  });
  it('coerces mixed types via string equality', () => {
    expect(propertyValueMatches(42, '42')).toBe(true);
    expect(propertyValueMatches(true, 'true')).toBe(true);
    expect(propertyValueMatches(false, 'True')).toBe(false);
  });
});

/* ── ruleMatchesElement ──────────────────────────────────────────────────── */

const baseRule = (over: Partial<SandboxRule> = {}): SandboxRule => ({
  element_type_filter: '',
  property_filter: {},
  quantity_source: 'area_m2',
  multiplier: '1',
  waste_factor_pct: '0',
  unit: 'm²',
  ...over,
});

describe('ruleMatchesElement', () => {
  it('matches everything when filter is empty or star', () => {
    const el: SandboxElement = { id: '1', element_type: 'Walls' };
    expect(ruleMatchesElement(baseRule(), el)).toBe(true);
    expect(ruleMatchesElement(baseRule({ element_type_filter: '*' }), el)).toBe(true);
  });
  it('matches one of a comma-separated filter list', () => {
    const el: SandboxElement = { id: '1', element_type: 'IfcWallStandardCase' };
    expect(ruleMatchesElement(baseRule({ element_type_filter: 'Wall*, IfcWall*' }), el)).toBe(true);
    const el2: SandboxElement = { id: '2', element_type: 'IfcSlab' };
    expect(ruleMatchesElement(baseRule({ element_type_filter: 'Wall*, IfcWall*' }), el2)).toBe(
      false,
    );
  });
  it('requires all property filters to pass', () => {
    const el: SandboxElement = {
      id: '1',
      element_type: 'Walls',
      properties: { material: 'concrete', loadBearing: true },
    };
    expect(
      ruleMatchesElement(baseRule({ property_filter: { material: 'concrete*' } }), el),
    ).toBe(true);
    expect(
      ruleMatchesElement(
        baseRule({ property_filter: { material: 'concrete*', loadBearing: 'false' } }),
        el,
      ),
    ).toBe(false);
  });
  it('rejects elements missing the typed element_type when a filter is set', () => {
    expect(ruleMatchesElement(baseRule({ element_type_filter: 'Wall*' }), { id: '1' })).toBe(false);
  });
});

/* ── quantity extraction + adjustment ────────────────────────────────────── */

describe('extractRawQuantity', () => {
  it('reads a quantity key', () => {
    const el: SandboxElement = { id: '1', quantities: { area_m2: 12.5 } };
    expect(extractRawQuantity(el, 'area_m2')).toBe(12.5);
  });
  it('returns 1 for count regardless of data', () => {
    expect(extractRawQuantity({ id: '1' }, 'count')).toBe(1);
  });
  it('reads property: sources', () => {
    const el: SandboxElement = { id: '1', properties: { net_area: '7.0' } };
    expect(extractRawQuantity(el, 'property:net_area')).toBe(7);
  });
  it('returns null for missing or non-numeric values', () => {
    expect(extractRawQuantity({ id: '1', quantities: {} }, 'area_m2')).toBeNull();
    expect(
      extractRawQuantity({ id: '1', properties: { x: 'not-a-number' } }, 'property:x'),
    ).toBeNull();
  });
});

describe('applyAdjustment', () => {
  it('applies multiplier and waste', () => {
    expect(applyAdjustment(100, '2', '0')).toBe(200);
    expect(applyAdjustment(100, '1', '5')).toBeCloseTo(105);
  });
  it('returns null on unparseable inputs', () => {
    expect(applyAdjustment(10, 'abc', '0')).toBeNull();
  });
  it('treats blank multiplier/waste as 1 / 0', () => {
    expect(applyAdjustment(10, '', '')).toBe(10);
  });
});

/* ── runSandbox end-to-end ───────────────────────────────────────────────── */

describe('runSandbox', () => {
  const elements: SandboxElement[] = [
    { id: 'a', element_type: 'Walls', stable_id: 'A', quantities: { area_m2: 10 } },
    { id: 'b', element_type: 'Walls', stable_id: 'B', quantities: { area_m2: 20 } },
    { id: 'c', element_type: 'Walls', stable_id: 'C', quantities: {} }, // no area -> skip
    { id: 'd', element_type: 'Floors', stable_id: 'D', quantities: { area_m2: 99 } }, // filtered out
  ];

  it('separates matches from skips and rolls up the total', () => {
    const res = runSandbox(
      baseRule({ element_type_filter: 'Walls', quantity_source: 'area_m2', waste_factor_pct: '10' }),
      elements,
    );
    expect(res.matches.map((m) => m.element_id).sort()).toEqual(['a', 'b']);
    expect(res.skips.map((s) => s.element_id)).toEqual(['c']);
    expect(res.skips[0]!.reason).toBe('missing_property');
    // (10 + 20) * 1 * 1.10 = 33
    expect(res.totalAdjusted).toBeCloseTo(33);
    expect(res.matchedTypes).toEqual(['Walls']);
    expect(res.scanned).toBe(4);
  });

  it('returns empty result when nothing matches', () => {
    const res = runSandbox(baseRule({ element_type_filter: 'Roofs' }), elements);
    expect(res.matches).toHaveLength(0);
    expect(res.skips).toHaveLength(0);
    expect(res.totalAdjusted).toBe(0);
  });
});

/* ── unit safety ─────────────────────────────────────────────────────────── */

describe('dimensionForSource / dimensionForUnit', () => {
  it('maps known sources', () => {
    expect(dimensionForSource('area_m2')).toBe('area');
    expect(dimensionForSource('volume_m3')).toBe('volume');
    expect(dimensionForSource('count')).toBe('count');
    expect(dimensionForSource('property:net_area')).toBe('unknown');
  });
  it('maps unit symbols tolerantly', () => {
    expect(dimensionForUnit('m²')).toBe('area');
    expect(dimensionForUnit('m2')).toBe('area');
    expect(dimensionForUnit('m³')).toBe('volume');
    expect(dimensionForUnit('m3')).toBe('volume');
    expect(dimensionForUnit('m')).toBe('length');
    expect(dimensionForUnit('kg')).toBe('weight');
    expect(dimensionForUnit('pcs')).toBe('count');
    expect(dimensionForUnit('blorp')).toBe('unknown');
  });
});

describe('checkUnitSafety', () => {
  it('flags an area source declared with a volume unit', () => {
    const r = checkUnitSafety('area_m2', 'm³');
    expect(r.mismatch).toBe(true);
    expect(r.ok).toBe(false);
    expect(r.sourceDimension).toBe('area');
    expect(r.unitDimension).toBe('volume');
  });
  it('passes when dimensions agree', () => {
    expect(checkUnitSafety('area_m2', 'm²').ok).toBe(true);
    expect(checkUnitSafety('volume_m3', 'm3').ok).toBe(true);
  });
  it('never raises a false alarm on unknown dimensions', () => {
    expect(checkUnitSafety('property:foo', 'm³').mismatch).toBe(false);
    expect(checkUnitSafety('area_m2', 'widgets').mismatch).toBe(false);
  });
});

/* ── coverage detector ───────────────────────────────────────────────────── */

describe('filterCoversCategory', () => {
  it('star and empty cover everything', () => {
    expect(filterCoversCategory('*', 'Walls')).toBe(true);
    expect(filterCoversCategory('', 'Walls')).toBe(true);
  });
  it('matches against any comma pattern', () => {
    expect(filterCoversCategory('Wall*, Floor*', 'Floors')).toBe(true);
    expect(filterCoversCategory('Wall*, Floor*', 'Roofs')).toBe(false);
  });
});

describe('buildCoverageReport', () => {
  const elements: SandboxElement[] = [
    { id: '1', element_type: 'Walls' },
    { id: '2', element_type: 'Walls' },
    { id: '3', element_type: 'Doors' },
    { id: '4', element_type: 'Roofs' },
    { id: '5', element_type: 'Roofs' },
    { id: '6', element_type: 'Roofs' },
  ];
  const rules: CoverageRule[] = [
    { name: 'Walls rule', element_type_filter: 'Wall*', is_active: true },
    { name: 'Doors rule', element_type_filter: 'Door*', is_active: false }, // disabled -> ignored
  ];

  it('flags categories with no active rule as uncovered, heaviest first', () => {
    const report = buildCoverageReport(elements, rules);
    expect(report.totalCategories).toBe(3);
    expect(report.coveredCategories).toBe(1);
    expect(report.coverageRatio).toBeCloseTo(1 / 3);
    // Uncovered = Doors + Roofs; sorted by element count desc -> Roofs first.
    expect(report.uncovered.map((r) => r.category)).toEqual(['Roofs', 'Doors']);
    const walls = report.rows.find((r) => r.category === 'Walls')!;
    expect(walls.covered).toBe(true);
    expect(walls.ruleNames).toEqual(['Walls rule']);
  });

  it('reports full coverage for an empty model', () => {
    const report = buildCoverageReport([], rules);
    expect(report.coverageRatio).toBe(1);
    expect(report.uncovered).toHaveLength(0);
  });
});

/* ── versioning ──────────────────────────────────────────────────────────── */

const fields = (over: Partial<RuleFormulaFields> = {}): RuleFormulaFields => ({
  element_type_filter: 'Walls',
  property_filter: { material: 'concrete' },
  quantity_source: 'area_m2',
  multiplier: '1',
  waste_factor_pct: '0',
  unit: 'm²',
  ...over,
});

describe('formulaSignature', () => {
  it('is order-independent over property_filter', () => {
    const a = fields({ property_filter: { a: '1', b: '2' } });
    const b = fields({ property_filter: { b: '2', a: '1' } });
    expect(formulaSignature(a)).toBe(formulaSignature(b));
  });
  it('changes when a formula field changes', () => {
    expect(formulaSignature(fields())).not.toBe(formulaSignature(fields({ multiplier: '2' })));
  });
});

describe('readVersions', () => {
  it('returns [] for missing or malformed metadata', () => {
    expect(readVersions(null)).toEqual([]);
    expect(readVersions({ versions: 'nope' })).toEqual([]);
    expect(readVersions({ versions: [{ no_saved_at: true }] })).toEqual([]);
  });
});

describe('pushVersion', () => {
  it('appends a snapshot when the formula changed', () => {
    const out = pushVersion([], fields(), { savedAt: '2026-01-01T00:00:00Z', label: 'v1' });
    expect(out).toHaveLength(1);
    expect(out[0]!.label).toBe('v1');
    expect(out[0]!.element_type_filter).toBe('Walls');
  });
  it('does not duplicate an identical most-recent snapshot', () => {
    const first = pushVersion([], fields(), { savedAt: 't1' });
    const second = pushVersion(first, fields(), { savedAt: 't2' });
    expect(second).toHaveLength(1);
  });
  it('caps history at 20 entries', () => {
    let hist = pushVersion([], fields({ multiplier: '1' }), { savedAt: 't0' });
    for (let i = 1; i <= 25; i += 1) {
      hist = pushVersion(hist, fields({ multiplier: String(i) }), { savedAt: `t${i}` });
    }
    expect(hist.length).toBe(20);
  });
});

/* ── draft confidence ────────────────────────────────────────────────────── */

describe('draftConfidence', () => {
  const mk = (matched: number, skipped: number) =>
    ({
      matches: Array.from({ length: matched }, (_, i) => ({
        element_id: `m${i}`,
        stable_id: '',
        element_type: 'Walls',
        name: '',
        raw_quantity: 1,
        adjusted_quantity: 1,
      })),
      skips: Array.from({ length: skipped }, (_, i) => ({
        element_id: `s${i}`,
        stable_id: '',
        element_type: 'Walls',
        reason: 'missing_property' as const,
      })),
      matchedTypes: ['Walls'],
      totalAdjusted: matched,
      scanned: matched + skipped,
    });

  it('is high when nearly all matches yield quantities', () => {
    expect(draftConfidence(mk(10, 0)).confidence).toBe('high');
    expect(draftConfidence(mk(9, 1)).confidence).toBe('high');
  });
  it('is medium in the middle band', () => {
    expect(draftConfidence(mk(7, 3)).confidence).toBe('medium');
  });
  it('is low when most matches drop out, or nothing matched', () => {
    expect(draftConfidence(mk(3, 7)).confidence).toBe('low');
    expect(draftConfidence(mk(0, 0)).confidence).toBe('low');
  });
});
