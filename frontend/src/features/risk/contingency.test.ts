// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers behind the contingency card and the finance budget note.
 *
 * Money arrives as Decimal strings; the cases below are the ones where a
 * string slipping into arithmetic, or a drawdown counted twice, would show a
 * wrong figure instead of failing loudly.
 */
import { describe, it, expect } from 'vitest';

import {
  CONTINGENCY_DRAWDOWN_PREFIX,
  canDrawContingency,
  drawnOnBudgetLine,
  isContingencyCategory,
  lineRemaining,
  money,
  parseAmountInput,
  type ContingencyLine,
} from './contingency';

describe('money', () => {
  it('reads Decimal strings and numbers, never NaN', () => {
    expect(money('2500.50')).toBe(2500.5);
    expect(money(12)).toBe(12);
    expect(money(null)).toBe(0);
    expect(money(undefined)).toBe(0);
    expect(money('abc')).toBe(0);
    // Two wire strings summed through money() add, they do not concatenate.
    expect(money('100.00') + money('150.00')).toBe(250);
  });
});

describe('parseAmountInput', () => {
  it.each([
    ['2500', '2500'],
    ['2500.75', '2500.75'],
    ['2500,75', '2500.75'],
    ['12 500,50', '12500.50'],
    ["12'500.50", '12500.50'],
    ['1.234.567,89', '1234567.89'],
    ['1,234,567.89', '1234567.89'],
  ])('accepts %s', (raw, expected) => {
    expect(parseAmountInput(raw)).toBe(expected);
  });

  it.each(['', '   ', '0', '-5', 'abc', '1e5', '12..5'])('rejects %s', (raw) => {
    expect(parseAmountInput(raw)).toBeNull();
  });
});

describe('canDrawContingency', () => {
  it('offers the drawdown to managers and admins only', () => {
    expect(canDrawContingency('manager')).toBe(true);
    expect(canDrawContingency('admin')).toBe(true);
    expect(canDrawContingency('owner')).toBe(true); // alias of admin
    expect(canDrawContingency('editor')).toBe(false);
    expect(canDrawContingency('estimator')).toBe(false); // alias of editor
    expect(canDrawContingency('viewer')).toBe(false);
    expect(canDrawContingency(null)).toBe(false);
    expect(canDrawContingency('mystery')).toBe(false);
  });
});

describe('isContingencyCategory', () => {
  it('matches both spellings and nothing else', () => {
    expect(isContingencyCategory('contingency')).toBe(true);
    expect(isContingencyCategory('Contingency')).toBe(true);
    expect(isContingencyCategory(' CONTINGENCY ')).toBe(true);
    expect(isContingencyCategory('material')).toBe(false);
    expect(isContingencyCategory(null)).toBe(false);
  });
});

describe('drawnOnBudgetLine', () => {
  it('sums the drawdown records and ignores every other metadata key', () => {
    const metadata = {
      notes: 'weather',
      budget_sync: '1',
      'sync:invoice:abc': '0|500',
      [`${CONTINGENCY_DRAWDOWN_PREFIX}risk:1`]: { amount: '2300.00', currency: 'EUR' },
      [`${CONTINGENCY_DRAWDOWN_PREFIX}risk:2`]: { amount: '700.50', currency: 'EUR' },
      [`${CONTINGENCY_DRAWDOWN_PREFIX}risk:3`]: '100',
      [`${CONTINGENCY_DRAWDOWN_PREFIX}risk:4`]: { amount: '-5' },
    };
    expect(drawnOnBudgetLine(metadata)).toEqual({ total: 3100.5, count: 3 });
  });

  it('is zero for an empty or missing object', () => {
    expect(drawnOnBudgetLine(null)).toEqual({ total: 0, count: 0 });
    expect(drawnOnBudgetLine({})).toEqual({ total: 0, count: 0 });
  });
});

describe('lineRemaining', () => {
  const lines: ContingencyLine[] = [
    { budget_id: 'a', wbs_id: null, currency: 'EUR', allocated: '1000', drawn: '300', remaining: '700.00', converted: true },
    { budget_id: 'b', wbs_id: 'B', currency: 'USD', allocated: '500', drawn: '0', remaining: '500.00', converted: true },
  ];
  it('returns the chosen line remaining as a number', () => {
    expect(lineRemaining(lines, 'a')).toBe(700);
    expect(lineRemaining(lines, 'b')).toBe(500);
    expect(lineRemaining(lines, 'zzz')).toBeNull();
    expect(lineRemaining(lines, null)).toBeNull();
  });
});
