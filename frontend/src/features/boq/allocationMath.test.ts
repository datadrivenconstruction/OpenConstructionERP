// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';

import { checkShares, normalizeShare, splitPreview } from './allocationMath';

describe('checkShares', () => {
  it('flags a share with more decimals than the backend stores', () => {
    expect(checkShares('percent', ['50.000001', '49.999999'], '0')).toMatchObject({ tooPrecise: false, addsUp: true });
    expect(checkShares('percent', ['50.0000001', '49.9999999'], '0').tooPrecise).toBe(true);
  });

  it('adds percent shares exactly and accepts a hundredth of a percent of slack', () => {
    expect(checkShares('percent', ['33.333', '33.333', '33.334'], '0')).toMatchObject({
      total: '100',
      addsUp: true,
    });
    // 99.995 is within 0.01 % of 100; 99.98 is not (the backend rule).
    expect(checkShares('percent', ['60', '39.995'], '0').addsUp).toBe(true);
    expect(checkShares('percent', ['60', '39.98'], '0')).toMatchObject({ addsUp: false, remaining: '0.02' });
  });

  it('compares quantity shares with the position quantity', () => {
    expect(checkShares('quantity', ['120', '180'], '300')).toMatchObject({ expected: '300', addsUp: true });
    expect(checkShares('quantity', ['120', '170'], '300')).toMatchObject({ addsUp: false, remaining: '10' });
    // No quantity, no quantity split.
    expect(checkShares('quantity', ['1'], '0').addsUp).toBe(false);
  });

  it('reads a decimal comma and refuses blanks, zero and negatives', () => {
    expect(checkShares('percent', ['50,5', '49,5'], '0').addsUp).toBe(true);
    expect(checkShares('percent', ['100', ''], '0').sharesValid).toBe(false);
    expect(checkShares('percent', ['120', '-20'], '0').sharesValid).toBe(false);
    expect(checkShares('percent', ['0', '100'], '0').addsUp).toBe(false);
    expect(normalizeShare(' 12,5 ')).toBe('12.5');
    expect(normalizeShare('abc')).toBeNull();
  });
});

describe('splitPreview', () => {
  it('splits to the cent and the parts add up', () => {
    expect(splitPreview('100.00', ['1', '1', '1'])).toEqual(['33.34', '33.33', '33.33']);
    expect(splitPreview('1000.01', ['33.333', '33.333', '33.334'])).toEqual(['333.33', '333.33', '333.35']);
  });

  it('keeps the sign of a credit and gives a blank share nothing', () => {
    expect(splitPreview('-10.00', ['50', '50'])).toEqual(['-5', '-5']);
    expect(splitPreview('10', ['100', ''])).toEqual(['10', '0']);
  });
});
