import { describe, expect, it } from 'vitest';
import { NEXT_STATUS, netTonnes, totalsOf } from '../model';

describe('haul ticket model', () => {
  it('computes net from gross and tare', () => {
    expect(netTonnes('32.4', '12.1')).toBe('20.3');
  });
  it('refuses tare above gross or missing weights', () => {
    expect(netTonnes('10', '12')).toBeNull();
    expect(netTonnes('', '5')).toBeNull();
  });
  it('skips rejected tickets in totals', () => {
    const t = totalsOf([
      { quantity: '10', amount: '100', status: 'verified' },
      { quantity: '5', amount: '50', status: 'rejected' },
    ]);
    expect(t).toEqual({ quantity: 10, amount: 100 });
  });
  it('has no way out of invoiced', () => {
    expect(NEXT_STATUS.invoiced).toEqual([]);
  });
});
