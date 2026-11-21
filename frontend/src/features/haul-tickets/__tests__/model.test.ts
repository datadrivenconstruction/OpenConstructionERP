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
      { net_t: '10', volume_m3: null, loads: 1, amount: '100', status: 'verified' },
      { net_t: '5', volume_m3: null, loads: 1, amount: '50', status: 'rejected' },
    ]);
    expect(t).toEqual({ tonnes: 10, volume: 0, loads: 1, amount: 100 });
  });
  it('never adds loads to tonnes', () => {
    // 672 t weighed plus 88 truck loads counted by the load must not read 760.
    const t = totalsOf([
      { net_t: '672', volume_m3: null, loads: 0, amount: '4872', status: 'verified' },
      { net_t: null, volume_m3: '1100', loads: 88, amount: '7040', status: 'delivered' },
    ]);
    expect(t).toEqual({ tonnes: 672, volume: 1100, loads: 88, amount: 11912 });
  });
  it('has no way out of invoiced', () => {
    expect(NEXT_STATUS.invoiced).toEqual([]);
  });
});
