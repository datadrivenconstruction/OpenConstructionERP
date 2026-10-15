// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import {
  addDecimalStrings,
  buildRequisitionLinesFromBuyList,
  mergeRequisitionLines,
  parseRequisitionRuleErrors,
  type RequisitionLineIn,
} from './requisitionsApi';

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
    expect(merged).not.toBeNull();
    expect(merged!.map((l) => l.quantity_requested)).toEqual(['10', '1']);
    expect(merged![0]!.sources.map((s) => s.resource_key)).toEqual(['4', '6']);
  });

  it('refuses lines in different units', () => {
    expect(mergeRequisitionLines([line('4', 't'), line('300', 'kg')], [0, 1])).toBeNull();
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
