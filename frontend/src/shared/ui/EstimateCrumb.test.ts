// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { revisionNumber } from './EstimateCrumb';

describe('revisionNumber', () => {
  const bills = [
    { id: 'a', parent_estimate_id: null },
    { id: 'b', parent_estimate_id: 'a' },
    { id: 'c', parent_estimate_id: 'b' },
    { id: 'x', parent_estimate_id: 'gone' },
    { id: 'l1', parent_estimate_id: 'l2' },
    { id: 'l2', parent_estimate_id: 'l1' },
  ];
  it('counts the revision chain from the original', () => {
    expect(revisionNumber(bills, 'a')).toBe(1);
    expect(revisionNumber(bills, 'c')).toBe(3);
  });
  it('stops at a missing parent and at a loop', () => {
    expect(revisionNumber(bills, 'x')).toBe(1);
    expect(revisionNumber(bills, 'l1')).toBeLessThan(4);
  });
});
