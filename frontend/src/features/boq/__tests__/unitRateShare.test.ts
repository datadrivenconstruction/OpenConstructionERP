// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `percentage_of_unit_rate` - the divisor is the position's stored
 * `unit_rate`, never the sum of its resources.
 *
 * The two are the same number whenever a position obeys the platform
 * invariant `unit_rate == sum(quantity * unit_rate)`, which is why most of
 * these cases would pass under either reading. The ones that matter are the
 * positions where the buildup and the rate disagree, and every such case here
 * is written twice over: once for the value it must produce, once for the
 * value it must NOT produce. The second half is the point. Dividing by the
 * resource sum makes the named roles add up to the divisor by construction, so
 * the column can never be wrong on its face and can therefore never report the
 * disagreement either - a share that is arithmetically incapable of being
 * surprising. Anyone tempted to "simplify" the divisor back to the resource
 * total will find those assertions in the way, and that is deliberate.
 *
 * Tested through the value getter rather than a mounted AG Grid, matching
 * `calculatedColumn.test.tsx`: the contract surface is the function that
 * `getCustomColumnDefs` returns.
 */

import { describe, it, expect } from 'vitest';
import type { ValueGetterParams } from 'ag-grid-community';
import { getCustomColumnDefs, type CustomColumnDef } from '../grid/columnDefs';
import type { Position } from '../api';

/* ── Fixtures ───────────────────────────────────────────────────── */

interface ResourceSeed {
  type: string;
  quantity: number;
  unit_rate: number;
}

function makePosition(
  id: string,
  unit_rate: number,
  resources: ResourceSeed[],
  quantity = 1,
): Position {
  return {
    id,
    boq_id: 'boq-1',
    parent_id: null,
    ordinal: '01.001',
    description: `pos ${id}`,
    unit: 'm3',
    quantity,
    unit_rate,
    total: quantity * unit_rate,
    classification: {},
    source: 'manual',
    confidence: null,
    sort_order: 0,
    validation_status: 'pending',
    metadata: {
      resources: resources.map((r, i) => ({
        name: `res-${i}`,
        unit: 'h',
        type: r.type,
        quantity: r.quantity,
        unit_rate: r.unit_rate,
      })),
    },
  };
}

/** The ÖNORM Lohn-Anteil column, the only shipped user of this hint. */
const LOHN_ANTEIL: CustomColumnDef = {
  name: 'lohn_anteil_pct',
  display_name: 'Lohn-Anteil %',
  column_type: 'number',
  derived: 'percentage_of_unit_rate',
  resource_role: 'labor',
};

function makeParams(row: unknown): ValueGetterParams {
  return { data: row } as unknown as ValueGetterParams;
}

/** Render one column against one row and return the displayed string. */
function render(col: CustomColumnDef, row: unknown, positions: Position[]): string {
  const defs = getCustomColumnDefs([col], { positions });
  const valueGetter = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
  return valueGetter(makeParams(row));
}

/** The cell classes the column asks for on this row. */
function renderClass(col: CustomColumnDef, row: unknown, positions: Position[]): string {
  const defs = getCustomColumnDefs([col], { positions });
  const cellClass = defs[0]!.cellClass as unknown as (p: unknown) => string;
  return cellClass({ data: row, colDef: defs[0] });
}

/* ── Tests ──────────────────────────────────────────────────────── */

describe('percentage_of_unit_rate divides by the unit rate', () => {
  it('agrees with the old resource-sum divisor when the buildup adds up', () => {
    // 40 labour + 60 material = 100, exactly the stored rate. This is the
    // case the platform invariant describes, and the change is a no-op here:
    // both divisors are 100. Every consistent position on a customer's screen
    // keeps the number it had.
    const pos = makePosition('a', 100, [
      { type: 'labor', quantity: 2, unit_rate: 20 },
      { type: 'material', quantity: 1, unit_rate: 60 },
    ]);
    expect(render(LOHN_ANTEIL, pos, [pos])).toBe('40.00');
  });

  it('measures a short buildup against the rate and NOT against the buildup', () => {
    // 30 labour + 30 material = 60 of direct cost under a rate of 100. The
    // honest labour share of what the customer pays is 30%. Dividing by the
    // buildup would print 50.00, which is the share of a number the customer
    // never sees, labelled as the share of one they do.
    const pos = makePosition('a', 100, [
      { type: 'labor', quantity: 1, unit_rate: 30 },
      { type: 'material', quantity: 1, unit_rate: 30 },
    ]);
    expect(render(LOHN_ANTEIL, pos, [pos])).toBe('30.00');
    expect(render(LOHN_ANTEIL, pos, [pos])).not.toBe('50.00');
  });

  it('measures an over-full buildup against the rate and NOT against the buildup', () => {
    // 80 labour + 80 material = 160 of direct cost under a rate of 100: the
    // position is quoted below what it costs to build. The labour alone is 80%
    // of the rate. Dividing by the buildup would print a comfortable 50.00 and
    // say nothing at all about a position that is losing money.
    const pos = makePosition('a', 100, [
      { type: 'labor', quantity: 1, unit_rate: 80 },
      { type: 'material', quantity: 1, unit_rate: 80 },
    ]);
    expect(render(LOHN_ANTEIL, pos, [pos])).toBe('80.00');
    expect(render(LOHN_ANTEIL, pos, [pos])).not.toBe('50.00');
  });

  it('prints a share above 100 rather than clamping it to a plausible number', () => {
    // Labour alone is worth more than the whole rate. 137.50 is not a valid
    // share of anything, and that is exactly what the reader needs to see: two
    // numbers stored on this position contradict each other. A clamp to 100.00
    // would rebuild the silence this divisor exists to break.
    const pos = makePosition('a', 80, [{ type: 'labor', quantity: 1, unit_rate: 110 }]);
    expect(render(LOHN_ANTEIL, pos, [pos])).toBe('137.50');
    expect(render(LOHN_ANTEIL, pos, [pos])).not.toBe('100.00');
  });

  it('marks the cell when the share cannot be true, and leaves it alone when it can', () => {
    const impossible = makePosition('a', 80, [{ type: 'labor', quantity: 1, unit_rate: 110 }]);
    expect(renderClass(LOHN_ANTEIL, impossible, [impossible])).toContain('bg-semantic-error-bg');

    // Exactly 100 is a position built entirely of labour, not a contradiction.
    const allLabour = makePosition('b', 100, [{ type: 'labor', quantity: 1, unit_rate: 100 }]);
    expect(renderClass(LOHN_ANTEIL, allLabour, [allLabour])).not.toContain('bg-semantic-error-bg');
    expect(render(LOHN_ANTEIL, allLabour, [allLabour])).toBe('100.00');
  });

  it('renders empty rather than a share of nothing when the rate is zero or absent', () => {
    // A share needs something to be a share OF. Zero, missing and unparseable
    // rates all render blank instead of dividing by zero into an Infinity or
    // quietly substituting the resource total as a stand-in divisor.
    const zero = makePosition('a', 0, [{ type: 'labor', quantity: 1, unit_rate: 40 }]);
    expect(render(LOHN_ANTEIL, zero, [zero])).toBe('');

    // A row straight off the wire, before anything normalised it: no rate at
    // all, then one that is not a number.
    const labourOnly = { resources: [{ type: 'labor', quantity: 1, unit_rate: 40 }] };
    expect(render(LOHN_ANTEIL, { id: 'b', metadata: labourOnly }, [])).toBe('');
    expect(render(LOHN_ANTEIL, { id: 'c', unit_rate: 'n/a', metadata: labourOnly }, [])).toBe('');
  });

  it('divides a resource sub-row by its PARENT rate, not by the resource own rate', () => {
    // A resource row carries a ``unit_rate`` of its own - the price of that
    // resource - so a divisor read off the row itself would always produce the
    // resource quantity as a percentage, which is meaningless. The parent has
    // to be resolved through ``_parentPositionId``.
    const parent = makePosition('p1', 200, [{ type: 'labor', quantity: 2, unit_rate: 25 }]);
    const resourceRow = {
      _isResource: true,
      _parentPositionId: 'p1',
      _resourceIndex: 0,
      _resourceName: 'res-0',
      _resourceType: 'labor',
      _resourceUnit: 'h',
      _resourceQty: 2,
      _resourceRate: 25,
      // The trap: the row's own rate is 25, and 2 * 25 / 25 * 100 would be 200.
      unit_rate: 25,
      quantity: 2,
    };
    // 2 h at 25 = 50 of a 200 rate.
    expect(render(LOHN_ANTEIL, resourceRow, [parent])).toBe('25.00');
    expect(render(LOHN_ANTEIL, resourceRow, [parent])).not.toBe('200.00');
    // And with the parent absent there is no rate to divide by at all.
    expect(render(LOHN_ANTEIL, resourceRow, [])).toBe('');
  });

  it('leaves resource_sum columns untouched - they report money, not a share', () => {
    // Control. ``resource_sum`` is the other derived kind and this change must
    // not reach it: the GAEB Lohn / Material / Geräte / Sonstiges split is a
    // set of amounts, and whether those amounts add up to the rate is the very
    // question the percentage column now answers.
    const sumCol: CustomColumnDef = {
      name: 'lohn_ep',
      display_name: 'Lohn-EP',
      column_type: 'number',
      derived: 'resource_sum',
      resource_role: 'labor',
    };
    const pos = makePosition('a', 100, [
      { type: 'labor', quantity: 1, unit_rate: 30 },
      { type: 'material', quantity: 1, unit_rate: 30 },
    ]);
    expect(render(sumCol, pos, [pos])).toBe('30.00');
    expect(renderClass(sumCol, pos, [pos])).not.toContain('bg-semantic-error-bg');
  });

  it('with no role set, reports the whole buildup against the rate', () => {
    // A column with no ``resource_role`` matches every resource, so it stops
    // being a trade share and becomes a reading of whether the position adds
    // up at all: 60 of buildup under a rate of 100 is 60.00, not a flat
    // 100.00. `presets.test.ts` forbids shipping such a column; this pins what
    // one would do if it existed.
    const noRole: CustomColumnDef = { ...LOHN_ANTEIL, resource_role: undefined };
    const pos = makePosition('a', 100, [
      { type: 'labor', quantity: 1, unit_rate: 30 },
      { type: 'material', quantity: 1, unit_rate: 30 },
    ]);
    expect(render(noRole, pos, [pos])).toBe('60.00');
    expect(render(noRole, pos, [pos])).not.toBe('100.00');
  });

  it('renders empty on a position with no resources at all', () => {
    const pos = makePosition('a', 100, []);
    expect(render(LOHN_ANTEIL, pos, [pos])).toBe('');
  });
});
