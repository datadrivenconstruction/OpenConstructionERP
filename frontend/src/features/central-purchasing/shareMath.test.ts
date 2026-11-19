import { describe, expect, it } from 'vitest';
import { checkShares, evenShares, fromUnits, toUnits } from './shareMath';

describe('checkShares, from the worked examples', () => {
  it('DE drywall: 5,200 + 2,800 + 4,000 covers 12,000 m2', () => {
    expect(checkShares('12000', ['5200', '2800', '4000'])).toEqual({
      sum: '12000',
      remaining: '0',
      blanks: 0,
      ok: true,
    });
  });

  it('UK containment: a blank share is not zero and the line is short by 500 m', () => {
    const check = checkShares('1100', ['600', null]);
    expect(check.blanks).toBe(1);
    expect(check.remaining).toBe('500');
    expect(check.ok).toBe(false);
  });

  it('a zero share answers the project and can make the line add up', () => {
    expect(checkShares('2400', ['2400', '0']).ok).toBe(true);
  });

  it('sums decimals without float drift', () => {
    expect(checkShares('0.3', ['0.1', '0.2']).ok).toBe(true);
    expect(checkShares('10.0001', ['5.0000', '5.0001']).ok).toBe(true);
  });
});

describe('decimal units', () => {
  it('round-trips and rejects junk', () => {
    expect(fromUnits(toUnits('1 234,5')!)).toBe('1234.5');
    expect(toUnits('abc')).toBeNull();
    expect(toUnits('')).toBeNull();
    expect(toUnits('1.23456')).toBeNull();
  });

  it('splits evenly with the remainder on the first projects', () => {
    expect(evenShares('3000', 2)).toEqual(['1500', '1500']);
    expect(evenShares('100', 3)).toEqual(['34', '33', '33']);
    expect(evenShares('10.5', 2)).toEqual(['5', '5.5']);
  });
});
