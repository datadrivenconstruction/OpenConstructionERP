import { describe, it, expect } from 'vitest';
import { monthSeries } from './CrmReports';
import { sourceLabel } from './crmLabels';

describe('monthSeries', () => {
  const rows = [
    { month: '2026-03', currency: 'USD', expected: '5500.00', deals: 2 },
    { month: '2026-04', currency: 'EUR', expected: '4000.00', deals: 1 },
    { month: '', currency: 'USD', expected: '100.00', deals: 1 },
  ];
  it('keeps one currency per chart and never adds currencies together', () => {
    expect(monthSeries(rows, 'USD')).toEqual([
      { month: '2026-03', expected: 5500, deals: 2 },
      { month: '', expected: 100, deals: 1 },
    ]);
    expect(monthSeries(rows, 'EUR')).toEqual([{ month: '2026-04', expected: 4000, deals: 1 }]);
  });
});

describe('sourceLabel', () => {
  const t = ((k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k) as never;
  it('names the trade show source and humanises unknown codes', () => {
    expect(sourceLabel(t, 'trade_show')).toBe('Trade show / exhibition');
    expect(sourceLabel(t, 'open_day')).toBe('open day');
  });
});
