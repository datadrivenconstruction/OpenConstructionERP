// @ts-nocheck
/**
 * Unit tests for BOQEditorPage utility functions.
 *
 * Tests cover the pure utility functions extracted/exported from BOQEditorPage:
 *   - evaluateFormula (via ./grid/cellEditors — single source of truth)
 *   - getCurrencySymbol
 *   - getVatRate
 *   - getLocaleForRegion
 *   - computeQualityScore
 *   - groupPositionsIntoSections + isSection (via ./api)
 *   - normalizePosition / normalizePositions (via ./api)
 */

import { describe, it, expect } from 'vitest';
import { evaluateFormula } from './grid/cellEditors';
import {
  getCurrencySymbol,
  getVatRate,
  getLocaleForRegion,
  computeQualityScore,
} from './BOQEditorPage';
import {
  groupPositionsIntoSections,
  isSection,
  normalizePosition,
  type Position,
  type Markup,
} from './api';

/* ── Position / Markup factories ──────────────────────────────────────── */

function makePosition(overrides: Partial<Position> = {}): Position {
  return {
    id: 'pos-1',
    boq_id: 'boq-1',
    parent_id: null,
    ordinal: '01.001',
    description: 'Test position',
    unit: 'm2',
    quantity: 10,
    unit_rate: 50,
    total: 500,
    classification: {},
    source: 'manual',
    confidence: null,
    validation_status: 'pending',
    sort_order: 0,
    metadata: {},
    ...overrides,
  };
}

function makeMarkup(overrides: Partial<Markup> = {}): Markup {
  return {
    id: 'markup-1',
    boq_id: 'boq-1',
    name: 'Overhead',
    percentage: 10,
    sort_order: 0,
    ...overrides,
  };
}

/* ── evaluateFormula ────────────────────────────────────────────────────── */

describe('evaluateFormula', () => {
  it('evaluates simple multiplication: 2*3 → 6', () => {
    expect(evaluateFormula('2*3')).toBe(6);
  });

  it('evaluates multi-factor multiplication: 2.5*3.0*12 → 90', () => {
    expect(evaluateFormula('2.5*3.0*12')).toBe(90);
  });

  it('evaluates expression with parentheses: (2+3)*4 → 20', () => {
    expect(evaluateFormula('(2+3)*4')).toBe(20);
  });

  it('evaluates division: 100/4 → 25', () => {
    expect(evaluateFormula('100/4')).toBe(25);
  });

  it('evaluates a plain number with no operator: 42 → 42', () => {
    expect(evaluateFormula('42')).toBe(42);
  });

  it('rounds result to 2 decimal places: 10/3 → 3.33', () => {
    expect(evaluateFormula('10/3')).toBe(3.33);
  });

  it('evaluates addition with spaces: 10 + 5 → 15', () => {
    expect(evaluateFormula('10 + 5')).toBe(15);
  });

  it('evaluates subtraction: 20 - 8 → 12', () => {
    expect(evaluateFormula('20 - 8')).toBe(12);
  });

  it('returns null for division by zero (Infinity)', () => {
    expect(evaluateFormula('1/0')).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(evaluateFormula('')).toBeNull();
  });

  it('returns null for letter-only input', () => {
    expect(evaluateFormula('hello')).toBeNull();
  });

  it('returns null for negative results (-5)', () => {
    // The parser handles unary minus but the result check requires result >= 0
    expect(evaluateFormula('-5')).toBeNull();
  });

  it('returns null for expression with unsafe characters', () => {
    expect(evaluateFormula('2 + alert(1)')).toBeNull();
    expect(evaluateFormula('require("fs")')).toBeNull();
  });

  it('evaluates nested parentheses: ((2+3)*2)+4 → 14', () => {
    expect(evaluateFormula('((2+3)*2)+4')).toBe(14);
  });
});

/* ── getCurrencySymbol ───────────────────────────────────────────────────── */

describe('getCurrencySymbol', () => {
  it('defaults to € when no argument provided', () => {
    expect(getCurrencySymbol()).toBe('€');
    expect(getCurrencySymbol(undefined)).toBe('€');
  });

  it('extracts symbol from parenthesised format: "EUR (€) — Euro" → "€"', () => {
    expect(getCurrencySymbol('EUR (€) — Euro')).toBe('€');
  });

  it('extracts multi-char symbol: "CAD (C$) — Canadian Dollar" → "C$"', () => {
    expect(getCurrencySymbol('CAD (C$) — Canadian Dollar')).toBe('C$');
  });

  it('looks up plain 3-letter code: "EUR" → "€"', () => {
    expect(getCurrencySymbol('EUR')).toBe('€');
  });

  it('looks up plain 3-letter code: "GBP" → "£"', () => {
    expect(getCurrencySymbol('GBP')).toBe('£');
  });

  it('looks up plain 3-letter code: "USD" → "$"', () => {
    expect(getCurrencySymbol('USD')).toBe('$');
  });

  it('returns the code itself when unknown (e.g. "XYZ")', () => {
    expect(getCurrencySymbol('XYZ')).toBe('XYZ');
  });

  it('is case-insensitive for plain codes: "eur" → "€"', () => {
    expect(getCurrencySymbol('eur')).toBe('€');
  });
});

/* ── getVatRate ──────────────────────────────────────────────────────────── */

describe('getVatRate', () => {
  it('returns 0.19 (German VAT) when no region provided', () => {
    expect(getVatRate()).toBe(0.19);
    expect(getVatRate(undefined)).toBe(0.19);
  });

  it('returns DACH VAT rate (19%) for Germany region', () => {
    expect(getVatRate('DACH (Germany, Austria, Switzerland)')).toBe(0.19);
  });

  it('returns UK VAT rate (20%)', () => {
    expect(getVatRate('United Kingdom')).toBe(0.20);
  });

  it('returns US VAT rate (0%)', () => {
    expect(getVatRate('United States')).toBe(0.0);
  });

  it('returns Australian GST (10%)', () => {
    expect(getVatRate('Australia')).toBe(0.10);
  });

  it('defaults to 0.19 for unknown region', () => {
    expect(getVatRate('Unknown Region XYZ')).toBe(0.19);
  });
});

/* ── getLocaleForRegion ──────────────────────────────────────────────────── */

describe('getLocaleForRegion', () => {
  it('defaults to "de-DE" when no region provided', () => {
    expect(getLocaleForRegion()).toBe('de-DE');
    expect(getLocaleForRegion(undefined)).toBe('de-DE');
  });

  it('returns "de-DE" for DACH region', () => {
    expect(getLocaleForRegion('DACH (Germany, Austria, Switzerland)')).toBe('de-DE');
  });

  it('returns "en-GB" for United Kingdom', () => {
    expect(getLocaleForRegion('United Kingdom')).toBe('en-GB');
  });

  it('returns "en-US" for United States', () => {
    expect(getLocaleForRegion('United States')).toBe('en-US');
  });

  it('returns "fr-FR" for France', () => {
    expect(getLocaleForRegion('France')).toBe('fr-FR');
  });

  it('returns "en-US" as fallback for unknown region', () => {
    expect(getLocaleForRegion('Unknown Region XYZ')).toBe('en-US');
  });
});

/* ── computeQualityScore ─────────────────────────────────────────────────── */

describe('computeQualityScore', () => {
  it('returns zero score with no non-section positions', () => {
    const result = computeQualityScore([], []);
    expect(result.score).toBe(0);
    expect(result.withDescription).toBe(0);
    expect(result.withQuantity).toBe(0);
    expect(result.withRate).toBe(0);
    expect(result.hasMarkups).toBe(false);
  });

  it('returns zero score when only section positions (no unit) are present', () => {
    const sectionPos = makePosition({ unit: '', quantity: 0, unit_rate: 0 });
    const result = computeQualityScore([sectionPos], []);
    expect(result.score).toBe(0);
  });

  it('reflects hasMarkups = true when markups array is non-empty', () => {
    const pos = makePosition({ description: 'Concrete', quantity: 10, unit_rate: 50 });
    const result = computeQualityScore([pos], [makeMarkup()]);
    expect(result.hasMarkups).toBe(true);
  });

  it('reflects hasMarkups = false when markups array is empty', () => {
    const pos = makePosition({ description: 'Concrete', quantity: 10, unit_rate: 50 });
    const result = computeQualityScore([pos], []);
    expect(result.hasMarkups).toBe(false);
  });

  it('computes 100% description coverage when all items have descriptions', () => {
    const positions = [
      makePosition({ id: 'p1', description: 'Excavation' }),
      makePosition({ id: 'p2', description: 'Formwork' }),
    ];
    const result = computeQualityScore(positions, []);
    expect(result.withDescription).toBe(100);
  });

  it('computes 50% description coverage when half the items have descriptions', () => {
    const positions = [
      makePosition({ id: 'p1', description: 'Excavation' }),
      makePosition({ id: 'p2', description: '' }),
    ];
    const result = computeQualityScore(positions, []);
    expect(result.withDescription).toBe(50);
  });

  it('computes full score (90) when all fields filled and no markups', () => {
    // 100% desc (30) + 100% qty (30) + 100% rate (30) + no markups (0) = 90
    const pos = makePosition({ description: 'Concrete wall', quantity: 50, unit_rate: 200 });
    const result = computeQualityScore([pos], []);
    expect(result.score).toBe(90);
  });

  it('computes full score (100) when all fields filled with markups', () => {
    // 100% desc (30) + 100% qty (30) + 100% rate (30) + markups (10) = 100
    const pos = makePosition({ description: 'Concrete wall', quantity: 50, unit_rate: 200 });
    const result = computeQualityScore([pos], [makeMarkup()]);
    expect(result.score).toBe(100);
  });

  it('excludes section-type positions (unit = "section") from score calculation', () => {
    const sectionPos = makePosition({ id: 'sec', unit: 'section', description: 'My Section', quantity: 0, unit_rate: 0 });
    const realPos = makePosition({ id: 'p1', unit: 'm2', description: 'Concrete', quantity: 5, unit_rate: 100 });
    const result = computeQualityScore([sectionPos, realPos], []);
    // Only realPos counts; score should be 90 (all desc/qty/rate filled, no markups)
    expect(result.score).toBe(90);
  });

  it('computes 0% quantity coverage when all quantities are zero', () => {
    const positions = [
      makePosition({ id: 'p1', quantity: 0 }),
      makePosition({ id: 'p2', quantity: 0 }),
    ];
    const result = computeQualityScore(positions, []);
    expect(result.withQuantity).toBe(0);
  });

  it('computes 100% rate coverage when all unit_rates are positive', () => {
    const positions = [
      makePosition({ id: 'p1', unit_rate: 100 }),
      makePosition({ id: 'p2', unit_rate: 250 }),
    ];
    const result = computeQualityScore(positions, []);
    expect(result.withRate).toBe(100);
  });
});

/* ── groupPositionsIntoSections (supplementary edge cases) ─────────────── */

describe('groupPositionsIntoSections — edge cases', () => {
  it('puts positions with an unresolvable parent_id into ungrouped', () => {
    const orphan = makePosition({ id: 'p1', parent_id: 'non-existent-section', total: 300 });
    const result = groupPositionsIntoSections([orphan]);
    expect(result.ungrouped).toHaveLength(1);
    expect(result.ungrouped[0].id).toBe('p1');
    expect(result.sections).toHaveLength(0);
  });

  it('accumulates subtotal correctly across multiple children', () => {
    const section = makePosition({
      id: 'sec-1', ordinal: '01', unit: '', quantity: 0, unit_rate: 0, total: 0, sort_order: 0,
    });
    const children = [
      makePosition({ id: 'c1', parent_id: 'sec-1', total: 100, sort_order: 10 }),
      makePosition({ id: 'c2', parent_id: 'sec-1', total: 200, sort_order: 20 }),
      makePosition({ id: 'c3', parent_id: 'sec-1', total: 50, sort_order: 30 }),
    ];
    const result = groupPositionsIntoSections([section, ...children]);
    expect(result.sections[0].subtotal).toBe(350);
  });

  it('returns empty sections and ungrouped for an empty input array', () => {
    const result = groupPositionsIntoSections([]);
    expect(result.sections).toHaveLength(0);
    expect(result.ungrouped).toHaveLength(0);
  });

  it('handles multiple sections each with their own children', () => {
    const sec1 = makePosition({ id: 's1', ordinal: '01', unit: '', total: 0, sort_order: 0 });
    const sec2 = makePosition({ id: 's2', ordinal: '02', unit: '', total: 0, sort_order: 10 });
    const child1 = makePosition({ id: 'p1', parent_id: 's1', total: 100, sort_order: 5 });
    const child2 = makePosition({ id: 'p2', parent_id: 's2', total: 200, sort_order: 15 });

    const result = groupPositionsIntoSections([sec1, sec2, child1, child2]);
    expect(result.sections).toHaveLength(2);
    expect(result.sections[0].children).toHaveLength(1);
    expect(result.sections[1].children).toHaveLength(1);
    expect(result.sections[0].subtotal).toBe(100);
    expect(result.sections[1].subtotal).toBe(200);
  });
});

/* ── isSection ──────────────────────────────────────────────────────────── */

describe('isSection', () => {
  it('returns true when unit is empty string', () => {
    expect(isSection(makePosition({ unit: '' }))).toBe(true);
  });

  it('returns true when unit is whitespace-only', () => {
    expect(isSection(makePosition({ unit: '   ' }))).toBe(true);
  });

  it('returns true when unit is "section" (case-insensitive)', () => {
    expect(isSection(makePosition({ unit: 'section' }))).toBe(true);
    expect(isSection(makePosition({ unit: 'SECTION' }))).toBe(true);
    expect(isSection(makePosition({ unit: 'Section' }))).toBe(true);
  });

  it('returns false when unit has a real measurement value', () => {
    expect(isSection(makePosition({ unit: 'm2' }))).toBe(false);
    expect(isSection(makePosition({ unit: 'm3' }))).toBe(false);
    expect(isSection(makePosition({ unit: 'pcs' }))).toBe(false);
    expect(isSection(makePosition({ unit: 'lsum' }))).toBe(false);
  });
});

/* ── normalizePosition ──────────────────────────────────────────────────── */

describe('normalizePosition', () => {
  it('returns position with existing metadata unchanged', () => {
    const pos = makePosition({ metadata: { formula: '2*5' } });
    expect(normalizePosition(pos).metadata).toEqual({ formula: '2*5' });
  });

  it('copies metadata_ to metadata when metadata is absent', () => {
    const pos = makePosition({
      metadata: undefined as unknown as Record<string, unknown>,
      metadata_: { source_row: 42 },
    });
    expect(normalizePosition(pos).metadata).toEqual({ source_row: 42 });
  });

  it('assigns empty object when both metadata and metadata_ are absent', () => {
    const pos = makePosition({ metadata: undefined as unknown as Record<string, unknown> });
    expect(normalizePosition(pos).metadata).toEqual({});
  });
});

/* ── Position total integrity ────────────────────────────────────────────── */

describe('Position total field', () => {
  it('total = quantity * unit_rate for a standard position', () => {
    const pos = makePosition({ quantity: 12, unit_rate: 25, total: 300 });
    expect(pos.total).toBe(pos.quantity * pos.unit_rate);
  });

  it('total is 0 when quantity is 0', () => {
    const pos = makePosition({ quantity: 0, unit_rate: 100, total: 0 });
    expect(pos.total).toBe(0);
  });

  it('total is 0 when unit_rate is 0', () => {
    const pos = makePosition({ quantity: 50, unit_rate: 0, total: 0 });
    expect(pos.total).toBe(0);
  });
});

/* ── Ordinal format ──────────────────────────────────────────────────────── */

describe('Ordinal format conventions', () => {
  it('section ordinal is zero-padded 2-digit string', () => {
    // Matches the padStart(2,'0') logic used in handleAddSection
    const sectionCount = 0;
    const ordinal = String(sectionCount + 1).padStart(2, '0');
    expect(ordinal).toBe('01');
  });

  it('second section ordinal is "02"', () => {
    const sectionCount = 1;
    const ordinal = String(sectionCount + 1).padStart(2, '0');
    expect(ordinal).toBe('02');
  });

  it('child position ordinal is "<parentOrdinal>.<childNum>"', () => {
    // Matches: `${parentOrdinal}.${String(childCount + 1).padStart(2, '0')}`
    const parentOrdinal = '01';
    const childCount = 0;
    const childNum = String(childCount + 1).padStart(2, '0');
    const ordinal = `${parentOrdinal}.${childNum}`;
    expect(ordinal).toBe('01.01');
  });

  it('third child in a section is "02.03"', () => {
    const parentOrdinal = '02';
    const childCount = 2;
    const childNum = String(childCount + 1).padStart(2, '0');
    const ordinal = `${parentOrdinal}.${childNum}`;
    expect(ordinal).toBe('02.03');
  });

  it('reorder ordinal uses 3-digit padding for children: "01.001"', () => {
    // Matches: `${sectionPrefix}.${String(idx + 1).padStart(3, '0')}` from handleReorderPositions
    const sectionPrefix = '01';
    const idx = 0;
    const newOrdinal = `${sectionPrefix}.${String(idx + 1).padStart(3, '0')}`;
    expect(newOrdinal).toBe('01.001');
  });
});
