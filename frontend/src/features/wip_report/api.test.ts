// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** The pure WIP helpers: exact decimal comparison, billing position, fade tone and sorting. */

import { describe, it, expect } from 'vitest';
import {
  billingPosition,
  compareDecimal,
  fadeTone,
  isValidAmount,
  isValidPeriod,
  latestPeriod,
  previousMonth,
  ruleKey,
  sortRows,
  type WipPeriod,
  type WipRow,
} from './api';

function row(over: Partial<WipRow>): WipRow {
  return {
    project_id: 'p',
    project_name: 'P',
    currency: 'EUR',
    over_billing: '0.00',
    under_billing: '0.00',
    fade: null,
    contract_value: '0.00',
    ...over,
  } as WipRow;
}

describe('compareDecimal', () => {
  it('compares exactly beyond float precision', () => {
    expect(compareDecimal('9007199254740993.01', '9007199254740993.02')).toBe(-1);
    expect(compareDecimal('0.1', '0.10')).toBe(0);
    expect(compareDecimal('-1.5', '-1.25')).toBe(-1);
    expect(compareDecimal('100', '99.99')).toBe(1);
  });
  it('treats missing or malformed values as zero', () => {
    expect(compareDecimal(null, '0')).toBe(0);
    expect(compareDecimal('abc', '1')).toBe(-1);
  });
});

describe('billingPosition', () => {
  it('names over, under and even', () => {
    expect(billingPosition({ over_billing: '10.00', under_billing: '0.00' })).toBe('over');
    expect(billingPosition({ over_billing: '0.00', under_billing: '0.01' })).toBe('under');
    expect(billingPosition({ over_billing: '0.00', under_billing: '0.00' })).toBe('even');
  });
});

describe('fadeTone', () => {
  it('marks negative as fade, positive as gain, the rest neutral', () => {
    expect(fadeTone('-5.00')).toBe('fade');
    expect(fadeTone('5.00')).toBe('gain');
    expect(fadeTone('0.00')).toBe('neutral');
    expect(fadeTone(null)).toBe('neutral');
  });
});

describe('sortRows', () => {
  it('sorts money exactly and keeps ties stable', () => {
    const rows = [
      row({ project_id: 'a', over_billing: '9.10' }),
      row({ project_id: 'b', over_billing: '10.00' }),
      row({ project_id: 'c', over_billing: '9.10' }),
    ];
    expect(sortRows(rows, 'over_billing', 'desc').map((r) => r.project_id)).toEqual(['b', 'a', 'c']);
    expect(sortRows(rows, 'over_billing', 'asc').map((r) => r.project_id)).toEqual(['a', 'c', 'b']);
  });
  it('puts a missing fade last in both directions', () => {
    const rows = [row({ project_id: 'a', fade: null }), row({ project_id: 'b', fade: '-2.00' }), row({ project_id: 'c', fade: '3.00' })];
    expect(sortRows(rows, 'fade', 'asc').map((r) => r.project_id)).toEqual(['b', 'c', 'a']);
    expect(sortRows(rows, 'fade', 'desc').map((r) => r.project_id)).toEqual(['c', 'b', 'a']);
  });
  it('does not mutate the input', () => {
    const rows = [row({ project_name: 'B' }), row({ project_name: 'A' })];
    sortRows(rows, 'project_name', 'asc');
    expect(rows[0]?.project_name).toBe('B');
  });
});

describe('periods', () => {
  it('defaults to the previous month, across a year boundary', () => {
    expect(previousMonth(new Date(2026, 0, 15))).toBe('2025-12');
    expect(previousMonth(new Date(2026, 9, 26))).toBe('2026-09');
  });
  it('validates period and amount input', () => {
    expect(isValidPeriod('2026-09')).toBe(true);
    expect(isValidPeriod('2026-13')).toBe(false);
    expect(isValidAmount('1200.50')).toBe(true);
    expect(isValidAmount('-1')).toBe(false);
    expect(isValidAmount('1,5')).toBe(false);
  });
  it('finds the latest closed period', () => {
    const ps = [{ period: '2026-07' }, { period: '2026-09' }, { period: '2026-08' }] as WipPeriod[];
    expect(latestPeriod(ps)?.period).toBe('2026-09');
    expect(latestPeriod([])).toBeNull();
  });
  it('strips the module prefix from a rule id', () => {
    expect(ruleKey('wip_report.loss_job')).toBe('loss_job');
  });
});
