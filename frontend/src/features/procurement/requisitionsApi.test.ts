// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import {
  addDecimalStrings,
  buildRequisitionLinesFromBuyList,
  canConvertTogether,
  lineToInput,
  mergeRequisitionLines,
  parseRequisitionRuleErrors,
  plannedConvertLines,
  isPositiveDecimal,
  type Requisition,
  type RequisitionLineIn,
} from './requisitionsApi';

describe('plannedConvertLines', () => {
  const item = (id: string, toOrder: string) =>
    ({ id, quantity_to_order: toOrder, quantity_outstanding: toOrder }) as Requisition['items'][number];
  const reqs = [{ items: [item('a', '71.4000'), item('b', '3.2500'), item('c', '0')] }];

  it('sends nothing when every open line takes what is still to order', () => {
    expect(plannedConvertLines(reqs, {})).toBeUndefined();
    expect(plannedConvertLines(reqs, { a: '71.4' })).toBeUndefined();
  });

  it('names each line with its quantity once one is changed or left out', () => {
    expect(plannedConvertLines(reqs, { a: '30' })).toEqual([
      { requisition_item_id: 'a', quantity: '30' },
      { requisition_item_id: 'b', quantity: '3.2500' },
    ]);
    expect(plannedConvertLines(reqs, { b: '' })).toEqual([{ requisition_item_id: 'a', quantity: '71.4000' }]);
    expect(plannedConvertLines(reqs, { a: '0', b: '' })).toEqual([]);
  });

  it('reads a positive decimal strictly', () => {
    expect(isPositiveDecimal('0.001')).toBe(true);
    expect(isPositiveDecimal('0.000')).toBe(false);
    expect(isPositiveDecimal('-1')).toBe(false);
    expect(isPositiveDecimal('1e3')).toBe(false);
    expect(isPositiveDecimal(null)).toBe(false);
  });
});

const P1 = '11111111-1111-4111-8111-111111111111';
const P2 = '22222222-2222-4222-8222-222222222222';
const CAT = '33333333-3333-4333-8333-333333333333';

const row = {
  name: 'Concrete C30/37',
  unit: 'm3',
  sources: [
    { position_id: P1, resource_key: '0:C30', quantity: '51.0000', unit: 'm3', catalog_item_id: null },
    { position_id: P2, resource_key: '0:C30', quantity: '20.4000', unit: 'm3', catalog_item_id: null },
  ],
};

describe('addDecimalStrings', () => {
  it('adds without float drift', () => {
    expect(addDecimalStrings('0.1', '0.2')).toBe('0.3');
    expect(addDecimalStrings('51.0000', '20.4000')).toBe('71.4000');
    expect(addDecimalStrings('1', '-1.5')).toBe('-0.5');
    expect(addDecimalStrings('x', '1')).toBeNull();
  });
});

describe('buildRequisitionLinesFromBuyList', () => {
  it('keeps uncoded sources apart unless the person confirms they are one material', () => {
    const apart = buildRequisitionLinesFromBuyList([row], { combineUncoded: false });
    expect(apart.map((l) => l.quantity_requested)).toEqual(['51.0000', '20.4000']);
    expect(apart.every((l) => l.sources.length === 1)).toBe(true);

    const together = buildRequisitionLinesFromBuyList([row], { combineUncoded: true });
    expect(together).toHaveLength(1);
    expect(together[0]!.quantity_requested).toBe('71.4000');
    expect(together[0]!.sources.map((s) => s.boq_position_id)).toEqual([P1, P2]);
  });

  it('always combines sources naming the same catalogue item', () => {
    const coded = {
      ...row,
      sources: row.sources.map((s) => ({ ...s, catalog_item_id: CAT })),
    };
    const lines = buildRequisitionLinesFromBuyList([coded], { combineUncoded: false });
    expect(lines).toHaveLength(1);
    expect(lines[0]!.catalog_item_id).toBe(CAT);
    expect(lines[0]!.quantity_requested).toBe('71.4000');
  });

  it('sends no position id for an anonymous position', () => {
    const anon = { ...row, sources: [{ ...row.sources[0]!, position_id: '__anon_0' }] };
    const [line] = buildRequisitionLinesFromBuyList([anon], { combineUncoded: false });
    expect(line!.sources[0]!.boq_position_id).toBeNull();
  });
});

describe('mergeRequisitionLines', () => {
  const line = (quantity: string, unit: string): RequisitionLineIn => ({
    description: 'Sand',
    unit,
    quantity_requested: quantity,
    sources: [{ boq_position_id: null, resource_key: quantity, quantity, unit }],
  });

  it('merges the chosen lines into the first and keeps every source', () => {
    const merged = mergeRequisitionLines([line('4', 't'), line('1', 't'), line('6', 't')], [2, 0]);
    expect(merged.ok).toBe(true);
    const lines = merged.ok ? merged.lines : [];
    expect(lines.map((l) => l.quantity_requested)).toEqual(['10', '1']);
    expect(lines[0]!.sources.map((s) => s.resource_key)).toEqual(['4', '6']);
  });

  it('refuses lines in different units', () => {
    expect(mergeRequisitionLines([line('4', 't'), line('300', 'kg')], [0, 1])).toEqual({
      ok: false,
      reason: 'unit_mismatch',
    });
  });
});

describe('parseRequisitionRuleErrors', () => {
  it('reads the rule failures of a refused submit', () => {
    const err = {
      body: { detail: { errors: [{ rule_id: 'procurement.requisition_source_unit', message: 'm', element_ref: '1' }] } },
    };
    expect(parseRequisitionRuleErrors(err)).toEqual([
      { rule_id: 'procurement.requisition_source_unit', message: 'm', element_ref: '1', suggestion: null },
    ]);
    expect(parseRequisitionRuleErrors(new Error('x'))).toEqual([]);
  });
});

describe('canConvertTogether', () => {
  const base = { status: 'approved' as const, project_id: 'p1', vendor_id: null as string | null };

  it('agrees on the one vendor the requisitions name, ignoring those that name none', () => {
    expect(canConvertTogether([{ ...base, vendor_id: 'v1' }, base])).toEqual({ ok: true, reason: null, vendorId: 'v1' });
    expect(canConvertTogether([base, base])).toEqual({ ok: true, reason: null, vendorId: null });
  });

  it('refuses an empty, unapproved, cross-project or two-vendor selection', () => {
    expect(canConvertTogether([]).reason).toBe('empty');
    expect(canConvertTogether([base, { ...base, status: 'submitted' }]).reason).toBe('not_approved');
    expect(canConvertTogether([base, { ...base, project_id: 'p2' }]).reason).toBe('mixed_projects');
    expect(canConvertTogether([{ ...base, vendor_id: 'v1' }, { ...base, vendor_id: 'v2' }]).reason).toBe(
      'vendor_conflict',
    );
  });
});

describe('lineToInput', () => {
  it('keeps the unit cost and currency, so saving a draft does not reset them', () => {
    const input = lineToInput({
      id: 'l1',
      description: 'Rebar B500B',
      unit: 't',
      quantity_requested: '12.5',
      quantity_ordered: '0',
      quantity_received: '0',
      quantity_consumed: '0',
      quantity_outstanding: '12.5',
      unit_cost: '845.50',
      currency_code: 'EUR',
      catalog_item_id: null,
      cost_line_id: null,
      sort_order: 0,
      sources: [],
    });
    expect(input.unit_cost).toBe('845.50');
    expect(input.currency_code).toBe('EUR');
    const other = { ...input, unit_cost: '900', quantity_requested: '1' };
    expect(mergeRequisitionLines([input, other], [0, 1])).toMatchObject({ ok: false, reason: 'needs_confirmation' });
    const merged = mergeRequisitionLines([input, other], [0, 1], { confirmed: true });
    expect(merged.ok && merged.lines[0]?.quantity_requested).toBe('13.5');
  });

  it('carries the line and source cost lines, so editing a draft does not lose them', () => {
    const input = lineToInput({
      id: 'l1',
      description: 'Rebar',
      unit: 't',
      quantity_requested: '2',
      quantity_ordered: '0',
      quantity_received: '0',
      quantity_consumed: '0',
      quantity_outstanding: '2',
      catalog_item_id: null,
      cost_line_id: 'cl-line',
      sort_order: 0,
      over_allocation_reason: 'Spare',
      sources: [
        { id: 's1', boq_position_id: 'p1', resource_key: '0', quantity: '2', unit: 't', cost_line_id: 'cl-src' },
      ],
    });
    expect(input.cost_line_id).toBe('cl-line');
    expect(input.sources[0]?.cost_line_id).toBe('cl-src');
    expect(input.over_allocation_reason).toBe('Spare');
  });
});

describe('merging lines that differ in cost, currency or cost line', () => {
  const line = (over: Partial<RequisitionLineIn> = {}): RequisitionLineIn => ({
    description: 'Rebar B500B',
    unit: 't',
    quantity_requested: '10',
    unit_cost: '800',
    currency_code: 'EUR',
    sources: [{ boq_position_id: 'p1', resource_key: '0', quantity: '10', unit: 't', cost_line_id: 'c1' }],
    ...over,
  });
  const foreign = () =>
    line({
      unit_cost: '900',
      currency_code: 'USD',
      sources: [{ boq_position_id: 'p2', resource_key: '0', quantity: '10', unit: 't', cost_line_id: 'c2' }],
    });

  it('merges lines that agree on cost, currency and cost line without asking', () => {
    const merged = mergeRequisitionLines([line(), line({ quantity_requested: '5' })], [0, 1]);
    expect(merged.ok && merged.lines).toHaveLength(1);
    expect(merged.ok && merged.lines[0]?.quantity_requested).toBe('15');
    expect(merged.ok && merged.lines[0]?.unit_cost).toBe('800');
  });

  it('refuses until confirmed when unit costs, currencies or cost lines differ, naming each', () => {
    expect(mergeRequisitionLines([line(), foreign()], [0, 1])).toEqual({
      ok: false,
      reason: 'needs_confirmation',
      conflicts: ['unit_cost', 'currency', 'cost_line'],
    });
  });

  it('keeps every source with its own cost line once confirmed, and leaves a mixed-currency line unpriced', () => {
    const merged = mergeRequisitionLines([line(), foreign()], [0, 1], { confirmed: true });
    expect(merged.ok).toBe(true);
    if (!merged.ok) return;
    expect(merged.lines[0]?.sources.map((s) => s.cost_line_id)).toEqual(['c1', 'c2']);
    expect(merged.lines[0]?.unit_cost).toBe('0');
    expect(merged.lines[0]?.currency_code).toBe('');
  });

  it('prices a confirmed merge at the quantity-weighted mean when the currency is one', () => {
    const merged = mergeRequisitionLines([line(), line({ unit_cost: '900', quantity_requested: '30' })], [0, 1], {
      confirmed: true,
    });
    expect(merged.ok && merged.lines[0]?.unit_cost).toBe('875');
    expect(merged.ok && merged.lines[0]?.currency_code).toBe('EUR');
  });

  it('never merges lines in different units, confirmed or not', () => {
    expect(mergeRequisitionLines([line(), line({ unit: 'kg' })], [0, 1], { confirmed: true })).toEqual({
      ok: false,
      reason: 'unit_mismatch',
    });
  });
});

describe('buy list to requisition: remaining quantity and estimated cost', () => {
  const P2 = '22222222-2222-4222-8222-222222222222';
  const src = (over: Record<string, unknown> = {}) => ({
    position_id: '11111111-1111-4111-8111-111111111111',
    resource_key: '0:C30',
    quantity: '51',
    unit: 'm3',
    unit_rate: '90',
    currency: 'EUR',
    covered_quantity: '0',
    remaining_quantity: '51',
    ...over,
  });

  it('asks for what is left, and skips a source with nothing left', () => {
    const row = {
      name: 'Concrete C30',
      unit: 'm3',
      sources: [
        src({ covered_quantity: '30', remaining_quantity: '21' }),
        src({ position_id: P2, remaining_quantity: '0' }),
        src({ position_id: '33333333-3333-4333-8333-333333333333', remaining_quantity: '-4' }),
      ],
    };
    const [line, ...rest] = buildRequisitionLinesFromBuyList([row], { combineUncoded: true });
    expect(rest).toEqual([]);
    expect(line?.quantity_requested).toBe('21');
    expect(line?.sources).toHaveLength(1);
    const whole = buildRequisitionLinesFromBuyList([row], { combineUncoded: true, useRemaining: false });
    expect(whole[0]?.quantity_requested).toBe('153');
  });

  it('prices a line at the quantity-weighted mean of its source rates in one currency', () => {
    const row = {
      name: 'Concrete C30',
      unit: 'm3',
      sources: [
        src({ quantity: '10', remaining_quantity: '10', unit_rate: '90' }),
        src({ position_id: P2, quantity: '30', remaining_quantity: '30', unit_rate: '110' }),
      ],
    };
    const [line] = buildRequisitionLinesFromBuyList([row], { combineUncoded: true });
    expect(line?.unit_cost).toBe('105');
    expect(line?.currency_code).toBe('EUR');
  });

  it('leaves the cost empty when a source has no rate or the currencies differ', () => {
    const noRate = { name: 'C30', unit: 'm3', sources: [src(), src({ position_id: P2, unit_rate: null })] };
    const mixed = { name: 'C30', unit: 'm3', sources: [src(), src({ position_id: P2, currency: 'USD' })] };
    for (const row of [noRate, mixed]) {
      const [line] = buildRequisitionLinesFromBuyList([row], { combineUncoded: true });
      expect(line?.unit_cost).toBeUndefined();
      expect(line?.currency_code).toBeUndefined();
    }
  });
});
