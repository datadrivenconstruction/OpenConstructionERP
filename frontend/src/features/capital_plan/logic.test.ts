// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';
import type { Envelope } from './api';
import { formatMoney, gapTone, isSingleSource, shiftedStart, withYearAmount } from './logic';

const env = (year: number, amount: string, label = ''): Envelope => ({
  id: `${year}-${label}`,
  plan_id: 'p',
  year,
  amount,
  label,
});

describe('capital plan logic', () => {
  it('reads a negative gap as a shortfall', () => {
    expect(gapTone('-0.01')).toBe('short');
    expect(gapTone('0.00')).toBe('even');
    expect(gapTone('12.50')).toBe('ok');
  });

  it('shifts the start year by whole years', () => {
    expect(shiftedStart({ start_year: 2030 }, 1)).toBe(2031);
    expect(shiftedStart({ start_year: 2030 }, -1)).toBe(2029);
  });

  it('formats money in the plan currency and survives an unknown code', () => {
    expect(formatMoney('1200000', 'EUR')).toMatch(/1[^0-9]?200[^0-9]?000/);
    expect(formatMoney('5', 'XX')).toBe('5');
    expect(formatMoney('not a number', 'EUR')).toBe('-');
  });

  it('replaces one year of the envelope and keeps the rest and the source label', () => {
    const out = withYearAmount([env(2030, '10', 'Bond'), env(2031, '20')], 2030, '99');
    expect(out).toEqual([
      { year: 2030, amount: '99', label: 'Bond' },
      { year: 2031, amount: '20', label: '' },
    ]);
    expect(withYearAmount([], 2032, '5')).toEqual([{ year: 2032, amount: '5', label: '' }]);
  });

  it('knows when a year has several funding sources', () => {
    const list = [env(2030, '1', 'Bond'), env(2030, '2', 'Grant'), env(2031, '3')];
    expect(isSingleSource(list, 2030)).toBe(false);
    expect(isSingleSource(list, 2031)).toBe(true);
    expect(isSingleSource(list, 2032)).toBe(true);
  });
});
