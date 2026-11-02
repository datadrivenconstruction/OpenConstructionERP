import { describe, expect, it } from 'vitest';
import { barHeight, fmtFactorPct, fmtNum, periodFor } from './productivityView';

describe('productivity view helpers', () => {
  // Wednesday 2026-11-04.
  const today = new Date(2026, 10, 4);

  it('builds Monday-to-Sunday periods', () => {
    expect(periodFor('this_week', today)).toEqual({ from: '2026-11-02', to: '2026-11-08' });
    expect(periodFor('last_week', today)).toEqual({ from: '2026-10-26', to: '2026-11-01' });
    expect(periodFor('last_4_weeks', today)).toEqual({ from: '2026-10-12', to: '2026-11-08' });
    expect(periodFor('month', today)).toEqual({ from: '2026-11-01', to: '2026-11-30' });
  });

  it('shows a dash for a figure that cannot be measured, never zero', () => {
    expect(fmtNum(null)).toBe('-');
    expect(fmtFactorPct(null)).toBe('-');
    expect(fmtFactorPct('1.2', 'en')).toBe('120%');
    expect(fmtNum('12.345', 1, 'en')).toBe('12.3');
  });

  it('scales trend bars against the busiest week', () => {
    expect(barHeight('10', 20)).toBe(50);
    expect(barHeight('0', 20)).toBe(0);
    expect(barHeight('0.1', 100)).toBe(4);
  });
});
