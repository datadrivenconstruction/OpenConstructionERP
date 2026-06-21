// @ts-nocheck
import { describe, it, expect } from 'vitest';
import {
  normalizePosition,
  normalizePositions,
  groupPositionsIntoSections,
  type Position,
} from './api';

/* ── Position factory ────────────────────────────────────────────────── */

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

/* ── normalizePosition ───────────────────────────────────────────────── */

describe('normalizePosition', () => {
  it('should return position unchanged if metadata exists', () => {
    const pos = makePosition({ metadata: { key: 'value' } });
    const result = normalizePosition(pos);
    expect(result.metadata).toEqual({ key: 'value' });
  });

  it('should copy metadata_ to metadata when metadata is missing', () => {
    const pos = makePosition({ metadata: undefined as unknown as Record<string, unknown>, metadata_: { legacy: true } });
    const result = normalizePosition(pos);
    expect(result.metadata).toEqual({ legacy: true });
  });

  it('should set empty metadata when both are missing', () => {
    const pos = makePosition({ metadata: undefined as unknown as Record<string, unknown> });
    const result = normalizePosition(pos);
    expect(result.metadata).toEqual({});
  });

  it('derives resource total from quantity * unit_rate when total is absent', () => {
    // Seed/import resources carry no `total` key - normalize must NOT inject
    // a literal 0 (that blanked the M/L/E split columns), it must derive the
    // per-unit money instead.
    const pos = makePosition({
      metadata: {
        resources: [
          { name: 'Concrete', type: 'material', quantity: 1, unit_rate: 75 },
          { name: 'Crew', type: 'labor', quantity: 0.7, unit_rate: 30 },
        ],
      },
    });
    const result = normalizePosition(pos);
    const resources = result.metadata.resources as Array<{ total: number }>;
    expect(resources[0].total).toBe(75);
    expect(resources[1].total).toBeCloseTo(21);
  });

  it('coerces a stored string-Decimal resource total instead of deriving', () => {
    // Issue #131 contract: resources that DO carry total keep it (coerced
    // from the API's exact decimal string to a number).
    const pos = makePosition({
      metadata: {
        resources: [
          { name: 'Pump', type: 'equipment', quantity: 2, unit_rate: 10, total: '60.0000' },
        ],
      },
    });
    const result = normalizePosition(pos);
    const resources = result.metadata.resources as Array<{ total: number }>;
    expect(resources[0].total).toBe(60); // NOT 20 (quantity * unit_rate)
  });

  it('derives the total when the stored total is null or empty string', () => {
    const pos = makePosition({
      metadata: {
        resources: [
          { name: 'A', type: 'material', quantity: 3, unit_rate: 5, total: null },
          { name: 'B', type: 'labor', quantity: 2, unit_rate: 4, total: '' },
        ],
      },
    });
    const result = normalizePosition(pos);
    const resources = result.metadata.resources as Array<{ total: number }>;
    expect(resources[0].total).toBe(15);
    expect(resources[1].total).toBe(8);
  });
});

/* ── normalizePositions ──────────────────────────────────────────────── */

describe('normalizePositions', () => {
  it('should normalize an array of positions', () => {
    const positions = [
      makePosition({ id: 'p1', metadata: { a: 1 } }),
      makePosition({ id: 'p2', metadata: undefined as unknown as Record<string, unknown>, metadata_: { b: 2 } }),
    ];
    const result = normalizePositions(positions);
    expect(result).toHaveLength(2);
    expect(result[0].metadata).toEqual({ a: 1 });
    expect(result[1].metadata).toEqual({ b: 2 });
  });

  it('should handle empty array', () => {
    expect(normalizePositions([])).toEqual([]);
  });
});

/* ── groupPositionsIntoSections ──────────────────────────────────────── */

describe('groupPositionsIntoSections', () => {
  it('should group positions under their parent section', () => {
    const section = makePosition({
      id: 'sec-1',
      ordinal: '01',
      description: 'Foundations',
      unit: '',
      quantity: 0,
      unit_rate: 0,
      total: 0,
      sort_order: 0,
    });
    const child1 = makePosition({
      id: 'pos-1',
      parent_id: 'sec-1',
      ordinal: '01.001',
      total: 100,
      sort_order: 10,
    });
    const child2 = makePosition({
      id: 'pos-2',
      parent_id: 'sec-1',
      ordinal: '01.002',
      total: 200,
      sort_order: 20,
    });

    const result = groupPositionsIntoSections([section, child1, child2]);
    expect(result.sections).toHaveLength(1);
    expect(result.sections[0].section.id).toBe('sec-1');
    expect(result.sections[0].children).toHaveLength(2);
    expect(result.sections[0].subtotal).toBe(300);
    expect(result.ungrouped).toHaveLength(0);
  });

  it('should put orphan positions in ungrouped', () => {
    const orphan = makePosition({ id: 'pos-1', parent_id: null, total: 500 });
    const result = groupPositionsIntoSections([orphan]);
    expect(result.ungrouped).toHaveLength(1);
    expect(result.ungrouped[0].id).toBe('pos-1');
    expect(result.sections).toHaveLength(0);
  });

  it('should handle mixed sections and ungrouped', () => {
    const section = makePosition({
      id: 'sec-1',
      ordinal: '01',
      description: 'Section 1',
      unit: '',
      quantity: 0,
      unit_rate: 0,
      total: 0,
    });
    const child = makePosition({
      id: 'pos-1',
      parent_id: 'sec-1',
      ordinal: '01.001',
      total: 100,
    });
    const orphan = makePosition({
      id: 'pos-2',
      parent_id: null,
      ordinal: '02.001',
      total: 200,
    });

    const result = groupPositionsIntoSections([section, child, orphan]);
    expect(result.sections).toHaveLength(1);
    expect(result.ungrouped).toHaveLength(1);
  });

  it('should sort sections by sort_order then ordinal', () => {
    const sec1 = makePosition({
      id: 'sec-1', ordinal: '02', description: 'B', unit: '', quantity: 0, unit_rate: 0, total: 0,
      sort_order: 20,
    });
    const sec2 = makePosition({
      id: 'sec-2', ordinal: '01', description: 'A', unit: '', quantity: 0, unit_rate: 0, total: 0,
      sort_order: 10,
    });

    const result = groupPositionsIntoSections([sec1, sec2]);
    expect(result.sections[0].section.id).toBe('sec-2');
    expect(result.sections[1].section.id).toBe('sec-1');
  });

  it('should handle empty array', () => {
    const result = groupPositionsIntoSections([]);
    expect(result.sections).toHaveLength(0);
    expect(result.ungrouped).toHaveLength(0);
  });

  /* ── Issue #150 — FX conversion in section subtotals ───────────────── */

  it('leaves subtotals unconverted when no fxOpts are passed (back-compat)', () => {
    // A child priced in a foreign currency must roll up VERBATIM with no FX
    // context — exactly the prior export/compare behaviour we must preserve.
    const section = makePosition({
      id: 'sec-1', ordinal: '01', description: 'S', unit: '', quantity: 0, unit_rate: 0, total: 0,
    });
    const child = makePosition({
      id: 'p1', parent_id: 'sec-1', ordinal: '01.001', total: 1000,
      metadata: { currency: 'USD' },
    });
    const result = groupPositionsIntoSections([section, child]);
    expect(result.sections[0].subtotal).toBe(1000);
  });

  it('converts a position-level foreign currency into base in the subtotal', () => {
    const section = makePosition({
      id: 'sec-1', ordinal: '01', description: 'S', unit: '', quantity: 0, unit_rate: 0, total: 0,
    });
    const child = makePosition({
      id: 'p1', parent_id: 'sec-1', ordinal: '01.001', total: 1000,
      metadata: { currency: 'USD' }, // 1 USD = 0.9 EUR
    });
    const result = groupPositionsIntoSections([section, child], {
      baseCurrency: 'EUR',
      fxRates: [{ currency: 'USD', rate: 0.9 }],
    });
    // 1000 USD × 0.9 = 900 EUR
    expect(result.sections[0].subtotal).toBeCloseTo(900);
  });

  it('converts a foreign-currency RESOURCE (no position currency) into base — Issue #150', () => {
    // The exact shape the contributor reported: the position has NO
    // metadata.currency, but its resource is priced in USD. Its stored total
    // was built from Σ(qty×rate) with no FX, so a naive sum would add it as
    // if "1 USD = 1 EUR". The resource-aware path must convert it.
    const section = makePosition({
      id: 'sec-1', ordinal: '01', description: 'S', unit: '', quantity: 0, unit_rate: 0, total: 0,
    });
    const child = makePosition({
      id: 'p1', parent_id: 'sec-1', ordinal: '01.001',
      quantity: 2,
      total: 200, // 2 × (1 × 100 USD), no FX baked in
      metadata: {
        // NOTE: no top-level currency here — the bug only bites this shape.
        resources: [
          { name: 'Imported pump', type: 'equipment', quantity: 1, unit_rate: 100, currency: 'USD' },
        ],
      },
    });
    const result = groupPositionsIntoSections([section, child], {
      baseCurrency: 'EUR',
      fxRates: [{ currency: 'USD', rate: 0.9 }],
    });
    // per-unit 100 USD × 0.9 = 90 EUR, × qty 2 = 180 EUR (NOT 200).
    expect(result.sections[0].subtotal).toBeCloseTo(180);
  });

  it('does not convert a base-currency resource', () => {
    const section = makePosition({
      id: 'sec-1', ordinal: '01', description: 'S', unit: '', quantity: 0, unit_rate: 0, total: 0,
    });
    const child = makePosition({
      id: 'p1', parent_id: 'sec-1', ordinal: '01.001', quantity: 2, total: 200,
      metadata: {
        resources: [
          { name: 'Local pump', type: 'equipment', quantity: 1, unit_rate: 100, currency: 'EUR' },
        ],
      },
    });
    const result = groupPositionsIntoSections([section, child], {
      baseCurrency: 'EUR',
      fxRates: [{ currency: 'USD', rate: 0.9 }],
    });
    expect(result.sections[0].subtotal).toBeCloseTo(200);
  });
});
