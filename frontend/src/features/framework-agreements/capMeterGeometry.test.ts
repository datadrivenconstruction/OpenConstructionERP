import { describe, expect, it } from 'vitest';
import { capMeterGeometry, capTone } from './capMeterGeometry';
import { parsePastedLines } from './status';
import { parsePriceList } from './CreateAgreementModal';

describe('cap meter', () => {
  it('places example 1 at 96.20 % in amber, past the 80 % threshold', () => {
    const g = capMeterGeometry({
      cap: '4000000.00',
      committed: '3848039.56',
      certified: '3120400.00',
      threshold_pct: '80',
      min_value: '1000000.00',
      term_elapsed_pct: '31.00',
    });
    expect(g.pct).toBe(96.2);
    expect(g.tone).toBe('warning');
    expect(g.threshold).toBe(80);
    expect(g.minimum).toBe(25);
    expect(g.certified + g.pending).toBeCloseTo(96.2, 1);
    expect(g.termElapsed).toBe(31);
  });

  it('grows the scale past the cap so example 3 shows its overrun in red', () => {
    const g = capMeterGeometry({ cap: '5000000.00', committed: '5008461.28', certified: '0', threshold_pct: '80' });
    expect(g.tone).toBe('error');
    expect(g.capMark).toBeLessThan(100);
    expect(g.certified + g.pending).toBe(100);
  });

  it('draws nothing to scale without a cap', () => {
    const g = capMeterGeometry({ cap: null, committed: '120.00', certified: '0', threshold_pct: '80' });
    expect(g.pct).toBeNull();
    expect(g.tone).toBe('neutral');
  });

  it('keeps tone neutral under the threshold', () => {
    expect(capTone(79.99, 80)).toBe('neutral');
    expect(capTone(80, 80)).toBe('warning');
    expect(capTone(100.01, 80)).toBe('error');
  });
});

describe('pasted rows', () => {
  it('reads code TAB qty lines from a spreadsheet and skips junk', () => {
    expect(parsePastedLines('01.010\t1\n01.020\t14\nheader\tqty\n01.030\t22,5\n\n')).toEqual([
      { code: '01.010', quantity: '1' },
      { code: '01.020', quantity: '14' },
      { code: '01.030', quantity: '22.5' },
    ]);
  });

  it('flags a price list code listed twice before it reaches the server', () => {
    const { items, duplicates } = parsePriceList(
      '01.010\tHouse connection\tSt\t1850.00\t1900\t2100\n01.020\tTrench\tm\t96,50\n01.010\tAgain\tSt\t1\n',
    );
    expect(items).toHaveLength(3);
    expect(items[0]).toMatchObject({ base_rate: '1850.00', estimated_qty: '1900', max_qty: '2100' });
    expect(items[1]!.base_rate).toBe('96.50');
    expect(duplicates).toEqual(['01.010']);
  });
});
