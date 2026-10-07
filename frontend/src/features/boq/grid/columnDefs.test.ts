// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import {
  getColumnDefs,
  needsPrice,
  nextResourceSplitMode,
  ordinalColumnWidth,
  resourceSplitFraction,
  resourceSplitMoneyTotals,
  resourceSplitPct,
  type BOQColumnContext,
} from './columnDefs';

/* ── resource-split toolbar tri-state cycle (pill -> columns -> off) ── */
describe('nextResourceSplitMode', () => {
  it('cycles pill -> columns -> off -> pill', () => {
    expect(nextResourceSplitMode('pill')).toBe('columns');
    expect(nextResourceSplitMode('columns')).toBe('off');
    expect(nextResourceSplitMode('off')).toBe('pill');
  });

  it('returns to the start after a full three-click loop', () => {
    const afterThree = nextResourceSplitMode(
      nextResourceSplitMode(nextResourceSplitMode('pill')),
    );
    expect(afterThree).toBe('pill');
  });
});

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

/* ── Ordinal ("Pos.") column width (K-2 in the German pilot QA) ──────────
 * The fixed 88px column ellipsised a standard German GAEB OZ ("01.01.0010")
 * to "01.01.0…" exactly where the narration pointed at the Ordnungszahl.
 * The width now derives from the longest ordinal in the grid: ~7.5px per
 * monospace character plus 30px cell chrome (padding + validation dot),
 * clamped so short ordinals keep the compact default.
 */
describe('ordinal column width', () => {
  const makeCtx = (maxOrdinalChars?: number): BOQColumnContext => ({
    currencySymbol: '€',
    currencyCode: 'EUR',
    locale: 'de-DE',
    fmt: new Intl.NumberFormat('de-DE'),
    t: (key: string, opts?: Record<string, string>) => (opts?.defaultValue as string) ?? key,
    ...(maxOrdinalChars !== undefined ? { maxOrdinalChars } : {}),
  });

  const ordinalWidth = (maxOrdinalChars?: number): number => {
    const col = getColumnDefs(makeCtx(maxOrdinalChars)).find((c) => c.field === 'ordinal');
    if (!col) throw new Error('ordinal column not found');
    return col.width as number;
  };

  it('fits a full German GAEB OZ like 01.01.0010 (10 chars) without truncation', () => {
    // 10 chars need >= ceil(10 * 7.5) + 30 = 105px of column.
    expect(ordinalColumnWidth(10)).toBeGreaterThanOrEqual(105);
    expect(ordinalWidth(10)).toBe(ordinalColumnWidth(10));
  });

  it('keeps the compact default when ordinals are short or unknown', () => {
    expect(ordinalWidth(undefined)).toBe(88);
    expect(ordinalWidth(0)).toBe(88);
    expect(ordinalWidth(5)).toBe(88);
  });

  it('grows monotonically with deeper OZ schemes', () => {
    expect(ordinalColumnWidth(13)).toBeGreaterThan(ordinalColumnWidth(10));
  });

  /* The floor moved off the old hardcoded 70px and now tracks the data. The
   * grid calls sizeColumnsToFit on ready and after every column change, and
   * that pass takes width back down to minWidth - so a 70px floor undid the
   * fitted width on any viewport that had to give space elsewhere, and
   * "09.01.0030" was ellipsised again. A GAEB OZ is an addressable
   * identifier that gets typed back into an inquiry, so the column is no
   * longer shrinkable below what its longest ordinal needs (widening still
   * works: `resizable: true` on defaultColDef). */
  it('cannot be squeezed below the width its longest ordinal needs', () => {
    const ordinalMinWidth = (maxOrdinalChars?: number): number => {
      const col = getColumnDefs(makeCtx(maxOrdinalChars)).find((c) => c.field === 'ordinal');
      if (!col) throw new Error('ordinal column not found');
      return col.minWidth as number;
    };
    // "09.01.0030" - a real GAEB Ordnungszahl, 10 characters.
    expect(ordinalMinWidth('09.01.0030'.length)).toBeGreaterThanOrEqual(105);
    expect(ordinalMinWidth(10)).toBe(ordinalWidth(10));
    expect(ordinalMinWidth(13)).toBe(ordinalWidth(13));
    // Nothing to size against keeps the historic compact column.
    expect(ordinalMinWidth(undefined)).toBe(88);
  });

  it('caps the width for pathological ordinals', () => {
    expect(ordinalColumnWidth(60)).toBe(180);
  });
});

/* ── Unit Rate editability (founder bug) ─────────────────────────────────
 * "If you change the Unit Rate on a position WITHOUT resources it does not
 * change. It only changes if you add and fill in resource prices." The cell
 * was locked whenever ANY non-empty resources array was present, including a
 * list of blank / zero-quantity placeholder rows. The rate cell must stay
 * editable until a resource with a non-zero quantity actually prices the line.
 */
describe('unit_rate column editability', () => {
  const ctx: BOQColumnContext = {
    currencySymbol: '€',
    currencyCode: 'EUR',
    locale: 'de-DE',
    fmt: new Intl.NumberFormat('de-DE'),
    t: (key: string, opts?: Record<string, string>) => (opts?.defaultValue as string) ?? key,
  };

  const isEditable = (data: Record<string, unknown>): boolean => {
    const col = getColumnDefs(ctx).find((c) => c.field === 'unit_rate');
    if (!col) throw new Error('unit_rate column not found');
    const raw = col.editable;
    if (typeof raw !== 'function') return !!raw;
    const ed = raw as unknown as (p: { data?: Record<string, unknown> }) => boolean;
    return ed({ data });
  };

  it('shows the project classification code without requiring a column toggle', () => {
    const context = { ...ctx, classificationStandard: 'gesn' };
    const column = getColumnDefs(context).find((candidate) => candidate.field === 'classification');
    expect(column).toBeDefined();
    expect(column?.hide).not.toBe(true);
    const getValue = column?.valueGetter as (params: {
      data: Record<string, unknown>;
      context: BOQColumnContext;
    }) => string;
    expect(getValue({ data: { classification: { gesn: '06-01-001-01' } }, context })).toBe('06-01-001-01');
    expect(getValue({ data: { _isSection: true, classification: { gesn: '06-01-001-01' } }, context })).toBe('');
  });

  it('is editable for a position with no resources', () => {
    expect(isEditable({ id: 'p1', unit_rate: 10, metadata: {} })).toBe(true);
  });

  it('is editable for an empty resources array', () => {
    expect(isEditable({ id: 'p1', unit_rate: 10, metadata: { resources: [] } })).toBe(true);
  });

  it('is editable for phantom / all-zero-quantity resources (the founder bug)', () => {
    expect(
      isEditable({
        id: 'p1',
        unit_rate: 10,
        metadata: { resources: [{ name: 'blank', quantity: 0, unit_rate: 0 }] },
      }),
    ).toBe(true);
  });

  it('is NOT editable once a resource has a non-zero quantity (invariant kept)', () => {
    expect(
      isEditable({
        id: 'p1',
        unit_rate: 60,
        metadata: { resources: [{ name: 'concrete', quantity: 2, unit_rate: 30 }] },
      }),
    ).toBe(false);
  });

  it('is not editable for section / footer rows', () => {
    expect(isEditable({ id: 's', _isSection: true })).toBe(false);
    expect(isEditable({ id: 'f', _isFooter: true })).toBe(false);
  });
});

/* ── needsPrice flag agrees with editability ─────────────────────────────
 * An unpriced line that is directly editable (no contributing resource) is
 * flagged amber; a resource-driven line never is.
 */
describe('needsPrice', () => {
  it('flags an unpriced line with no resources', () => {
    expect(needsPrice({ unit: 'm2', unit_rate: 0, metadata: {} })).toBe(true);
  });

  it('flags an unpriced line carrying only blank / zero-quantity resources', () => {
    expect(
      needsPrice({ unit: 'm2', unit_rate: 0, metadata: { resources: [{ quantity: 0, unit_rate: 0 }] } }),
    ).toBe(true);
  });

  it('does not flag a resource-driven line', () => {
    expect(
      needsPrice({ unit: 'm2', unit_rate: 60, metadata: { resources: [{ quantity: 2, unit_rate: 30 }] } }),
    ).toBe(false);
  });

  it('does not flag a manually priced line', () => {
    expect(needsPrice({ unit: 'm2', unit_rate: 42, metadata: {} })).toBe(false);
  });
});
