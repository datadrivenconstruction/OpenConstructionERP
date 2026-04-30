/**
 * Phase E v2.7.0/E — Calculated custom column type.
 *
 * We test the column def's valueGetter directly (not via a full AG Grid
 * mount) because the contract surface is the function returned by
 * `getCustomColumnDefs`. Mounting AG Grid in jsdom is heavy and brittle —
 * the formula evaluation path is already covered by the engine tests; what
 * matters here is that:
 *
 *   • A 'calculated' column produces a properly-formatted string for a
 *     normal row, and respects the `decimals` knob.
 *   • Cross-position references via `pos("…")` resolve against the
 *     positions array threaded through `getCustomColumnDefs`.
 *   • Self-referential `col("self")` formulas return the `#CYCLE` sentinel
 *     instead of recursing.
 *   • Syntax errors return `#ERR` rather than throwing.
 *   • Text/number columns still work (no regression in the legacy paths).
 */

import { describe, it, expect } from 'vitest';
import type { ValueGetterParams } from 'ag-grid-community';
import {
  getCustomColumnDefs,
  type CustomColumnDef,
} from '../grid/columnDefs';
import type { Position } from '../api';

/* ── Fixtures ───────────────────────────────────────────────────── */

function makePosition(opts: Partial<Position> & { id: string; ordinal: string }): Position {
  return {
    id: opts.id,
    boq_id: 'boq-1',
    parent_id: null,
    ordinal: opts.ordinal,
    description: opts.description ?? `pos ${opts.ordinal}`,
    unit: opts.unit ?? 'm',
    quantity: opts.quantity ?? 0,
    unit_rate: opts.unit_rate ?? 0,
    total: (opts.quantity ?? 0) * (opts.unit_rate ?? 0),
    classification: {},
    source: 'manual',
    confidence: null,
    sort_order: 0,
    validation_status: 'pending',
    metadata: opts.metadata ?? {},
  };
}

/**
 * Minimal stub for AG Grid's `ValueGetterParams` — the column def only
 * reads `params.data`, so this is enough.  We use a typed cast to a
 * `Pick<ValueGetterParams, 'data'>` so we never reach for `any`.
 */
function makeParams(row: Position): ValueGetterParams {
  return { data: row } as unknown as ValueGetterParams;
}

/* ── Tests ──────────────────────────────────────────────────────── */

describe('getCustomColumnDefs — calculated columns', () => {
  it('renders a row-local formula with default 2 decimals', () => {
    const col: CustomColumnDef = {
      name: 'with_vat',
      display_name: 'With VAT',
      column_type: 'calculated',
      formula: '=$QUANTITY * $UNIT_RATE * 1.19',
    };
    const row = makePosition({ id: 'a', ordinal: '1.1', quantity: 10, unit_rate: 5 });
    const defs = getCustomColumnDefs([col], { positions: [row] });
    expect(defs).toHaveLength(1);
    const valueGetter = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    const result = valueGetter(makeParams(row));
    // 10 * 5 * 1.19 = 59.5 → "59.50" with 2 decimals
    expect(result).toBe('59.50');
  });

  it('respects an explicit `decimals` setting', () => {
    const col: CustomColumnDef = {
      name: 'precise',
      display_name: 'Precise',
      column_type: 'calculated',
      formula: '=$QUANTITY / 3',
      decimals: 4,
    };
    const row = makePosition({ id: 'a', ordinal: '1.1', quantity: 1 });
    const defs = getCustomColumnDefs([col], { positions: [row] });
    const valueGetter = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    expect(valueGetter(makeParams(row))).toBe('0.3333');
  });

  it('clamps decimals to 0..6', () => {
    const col: CustomColumnDef = {
      name: 'clamped',
      display_name: 'Clamped',
      column_type: 'calculated',
      formula: '=$QUANTITY / 3',
      decimals: 99,
    };
    const row = makePosition({ id: 'a', ordinal: '1.1', quantity: 1 });
    const defs = getCustomColumnDefs([col], { positions: [row] });
    const vg = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    // Engine rounds to 4 decimals internally, then we format to 6 max.
    // Output therefore has 6 chars after the dot.
    expect(vg(makeParams(row))).toMatch(/^0\.\d{6}$/);
  });

  it('resolves cross-position refs via pos("ordinal")', () => {
    const col: CustomColumnDef = {
      name: 'ratio',
      display_name: 'Ratio',
      column_type: 'calculated',
      // Pull qty from a sibling row → divide by current qty.
      formula: '=pos("01.005").qty / $QUANTITY',
    };
    const sibling = makePosition({ id: 's', ordinal: '01.005', quantity: 100 });
    const current = makePosition({ id: 'c', ordinal: '01.001', quantity: 25 });
    const defs = getCustomColumnDefs([col], { positions: [sibling, current] });
    const vg = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    expect(vg(makeParams(current))).toBe('4.00');
  });

  it('updates when the source row changes (re-evaluates on each call)', () => {
    const col: CustomColumnDef = {
      name: 'live',
      display_name: 'Live',
      column_type: 'calculated',
      formula: '=pos("01.005").qty * 2',
    };
    let sibling = makePosition({ id: 's', ordinal: '01.005', quantity: 10 });
    const current = makePosition({ id: 'c', ordinal: '01.001' });
    let defs = getCustomColumnDefs([col], { positions: [sibling, current] });
    let vg = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    expect(vg(makeParams(current))).toBe('20.00');

    // Mutate the sibling and rebuild defs (mirrors what BOQGrid does on
    // every positions change).
    sibling = { ...sibling, quantity: 50 };
    defs = getCustomColumnDefs([col], { positions: [sibling, current] });
    vg = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    expect(vg(makeParams(current))).toBe('100.00');
  });

  it('returns #CYCLE when a formula references its own column via col()', () => {
    const col: CustomColumnDef = {
      name: 'self_loop',
      display_name: 'Self Loop',
      column_type: 'calculated',
      formula: '=col("self_loop") + 1',
    };
    const row = makePosition({ id: 'a', ordinal: '1.1' });
    const defs = getCustomColumnDefs([col], { positions: [row] });
    const vg = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    expect(vg(makeParams(row))).toBe('#CYCLE');
  });

  it('returns #ERR for unknown identifiers / functions', () => {
    const col: CustomColumnDef = {
      name: 'broken',
      display_name: 'Broken',
      column_type: 'calculated',
      formula: '=does_not_exist(42)',
    };
    const row = makePosition({ id: 'a', ordinal: '1.1' });
    const defs = getCustomColumnDefs([col], { positions: [row] });
    const vg = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    expect(vg(makeParams(row))).toBe('#ERR');
  });

  it('returns "" for empty formula', () => {
    const col: CustomColumnDef = {
      name: 'noop',
      display_name: 'Noop',
      column_type: 'calculated',
      formula: '',
    };
    const row = makePosition({ id: 'a', ordinal: '1.1', quantity: 5 });
    const defs = getCustomColumnDefs([col], { positions: [row] });
    const vg = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    expect(vg(makeParams(row))).toBe('');
  });

  it('is read-only (editable=false) and prefixes the header with ƒ', () => {
    const col: CustomColumnDef = {
      name: 'ro',
      display_name: 'Tax',
      column_type: 'calculated',
      formula: '=$QUANTITY * 0.19',
    };
    const defs = getCustomColumnDefs([col], { positions: [] });
    expect(defs[0]!.editable).toBe(false);
    expect(defs[0]!.headerName).toBe('ƒ Tax');
  });

  it('skips section / footer rows', () => {
    const col: CustomColumnDef = {
      name: 'skip',
      display_name: 'Skip',
      column_type: 'calculated',
      formula: '=$QUANTITY * 2',
    };
    const defs = getCustomColumnDefs([col], { positions: [] });
    const vg = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    expect(
      vg({ data: { _isSection: true, quantity: 10 } } as unknown as ValueGetterParams),
    ).toBe('');
    expect(
      vg({ data: { _isFooter: true, quantity: 10 } } as unknown as ValueGetterParams),
    ).toBe('');
  });

  it('resolves $-variables passed in the engine context', () => {
    const col: CustomColumnDef = {
      name: 'with_var',
      display_name: 'With Var',
      column_type: 'calculated',
      formula: '=$QUANTITY * $LABOR_RATE',
    };
    const row = makePosition({ id: 'a', ordinal: '1.1', quantity: 8 });
    const defs = getCustomColumnDefs([col], {
      positions: [row],
      variables: new Map([['LABOR_RATE', { type: 'number', value: 12.5 }]]),
    });
    const vg = defs[0]!.valueGetter as (p: ValueGetterParams) => string;
    expect(vg(makeParams(row))).toBe('100.00');
  });
});

describe('getCustomColumnDefs — backwards compatibility', () => {
  it('still produces editable text columns', () => {
    const col: CustomColumnDef = { name: 'note', display_name: 'Note', column_type: 'text' };
    const defs = getCustomColumnDefs([col]);
    expect(defs[0]!.cellEditor).toBe('agTextCellEditor');
    // editable is a function for non-calculated columns; check it's not
    // the literal `false` we use for calculated cols.
    expect(defs[0]!.editable).not.toBe(false);
  });

  it('still produces editable number columns', () => {
    const col: CustomColumnDef = { name: 'qty2', display_name: 'Qty2', column_type: 'number' };
    const defs = getCustomColumnDefs([col]);
    expect(defs[0]!.cellEditor).toBe('agNumberCellEditor');
  });

  it('treats rows without column_type as text (legacy migration)', () => {
    // Cast through unknown to simulate a legacy persisted row that
    // pre-dates the column_type field.
    const legacy = { name: 'old', display_name: 'Old' } as unknown as CustomColumnDef;
    const defs = getCustomColumnDefs([legacy]);
    expect(defs[0]!.cellEditor).toBe('agTextCellEditor');
  });
});
