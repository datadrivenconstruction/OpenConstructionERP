import { describe, it, expect } from 'vitest';
import { resourceSplitFraction, resourceSplitPct, resourceSplitMoneyTotals } from './columnDefs';

/* ── resourceSplitPct / resourceSplitFraction ───────────────────────── */

describe('resourceSplitPct', () => {
  it('computes the split from live resources with numeric totals', () => {
    const meta = {
      resources: [
        { type: 'material', total: 75 },
        { type: 'labor', total: 21 },
        { type: 'equipment', total: 4 },
      ],
    };
    expect(resourceSplitPct(meta, 'material')).toBe(75);
    expect(resourceSplitPct(meta, 'labor')).toBe(21);
    expect(resourceSplitPct(meta, 'equipment')).toBe(4);
  });

  it('derives quantity * unit_rate for resources without a total', () => {
    const meta = {
      resources: [
        { type: 'material', quantity: 1, unit_rate: 75 },
        { type: 'labor', quantity: 0.7, unit_rate: 30 },
        { type: 'equipment', quantity: 0.1, unit_rate: 40 },
      ],
    };
    expect(resourceSplitPct(meta, 'material')).toBe(75);
    expect(resourceSplitPct(meta, 'labor')).toBe(21);
    expect(resourceSplitPct(meta, 'equipment')).toBe(4);
  });

  it('falls back to resource_breakdown when live totals are all zero', () => {
    // Regression: normalize used to inject total: 0 into every resource,
    // which made the loop see subtotal 0 and return null even though the
    // server-side rollup knew the split. Zeroed resources must fall through.
    const meta = {
      resources: [
        { type: 'material', total: 0, quantity: 0, unit_rate: 0 },
        { type: 'labor', total: 0, quantity: 0, unit_rate: 0 },
      ],
      resource_breakdown: {
        material: { total: 75, pct: 75 },
        labor: { total: 21, pct: 21 },
        equipment: { total: 4, pct: 4 },
      },
    };
    expect(resourceSplitPct(meta, 'material')).toBe(75);
    expect(resourceSplitPct(meta, 'labor')).toBe(21);
    expect(resourceSplitPct(meta, 'equipment')).toBe(4);
  });

  it('uses resource_breakdown when no resources array exists', () => {
    const meta = {
      resource_breakdown: { material: { total: 50, pct: 50.4 } },
    };
    expect(resourceSplitPct(meta, 'material')).toBe(50);
    expect(resourceSplitPct(meta, 'labor')).toBeNull();
  });

  it('returns null when the position has no resource data at all', () => {
    expect(resourceSplitPct({}, 'material')).toBeNull();
  });
});

describe('resourceSplitFraction', () => {
  it('returns the exact (unrounded) fraction', () => {
    const meta = {
      resources: [
        { type: 'material', total: 1 },
        { type: 'labor', total: 2 },
      ],
    };
    expect(resourceSplitFraction(meta, 'material')).toBeCloseTo(1 / 3);
    expect(resourceSplitFraction(meta, 'labor')).toBeCloseTo(2 / 3);
  });

  it('maps resource_breakdown pct to a fraction', () => {
    const meta = { resource_breakdown: { labor: { pct: 21 } } };
    expect(resourceSplitFraction(meta, 'labor')).toBeCloseTo(0.21);
  });
});

/* ── resourceSplitMoneyTotals (footer rollup) ───────────────────────── */

describe('resourceSplitMoneyTotals', () => {
  const position = (over: Record<string, unknown>) => ({
    unit: 'm3',
    quantity: 10,
    unit_rate: 100,
    metadata: {},
    ...over,
  });

  it('aggregates share x unit_rate x quantity per type across leaf positions', () => {
    const positions = [
      position({
        metadata: {
          resources: [
            { type: 'material', quantity: 1, unit_rate: 75 },
            { type: 'labor', quantity: 0.7, unit_rate: 30 },
            { type: 'equipment', quantity: 0.1, unit_rate: 40 },
          ],
        },
      }),
      position({
        quantity: 2,
        unit_rate: 50,
        metadata: { resource_breakdown: { material: { pct: 50 }, labor: { pct: 50 } } },
      }),
    ];
    const totals = resourceSplitMoneyTotals(positions);
    expect(totals).not.toBeNull();
    // Pos 1: total 1000 -> 750 / 210 / 40. Pos 2: total 100 -> 50 / 50 / 0.
    expect(totals!.material).toBeCloseTo(800);
    expect(totals!.labor).toBeCloseTo(260);
    expect(totals!.equipment).toBeCloseTo(40);
  });

  it('skips section rows so children are not double counted', () => {
    const positions = [
      position({ unit: '', metadata: { resource_breakdown: { material: { pct: 100 } } } }),
      position({
        metadata: { resource_breakdown: { material: { pct: 100 } } },
      }),
    ];
    const totals = resourceSplitMoneyTotals(positions);
    expect(totals!.material).toBeCloseTo(1000); // only the leaf (10 x 100)
  });

  it('returns null when no position carries a split', () => {
    expect(resourceSplitMoneyTotals([position({}), position({ metadata: {} })])).toBeNull();
  });
});
