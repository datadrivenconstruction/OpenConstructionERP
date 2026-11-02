import { describe, it, expect } from 'vitest';
import { quantityFractionDigits, isCountUnit } from './quantityFormat';

describe('quantityFractionDigits', () => {
  it('shows three fixed decimals for measured units', () => {
    expect(quantityFractionDigits(2.625, 'm3')).toEqual({ min: 3, max: 3 });
    expect(quantityFractionDigits(12, 'm2')).toEqual({ min: 3, max: 3 });
  });

  it('shows whole counted units without decimals', () => {
    expect(quantityFractionDigits(12, 'pcs')).toEqual({ min: 0, max: 0 });
    expect(quantityFractionDigits(3, 'Stk')).toEqual({ min: 0, max: 0 });
    expect(quantityFractionDigits(3, 'шт')).toEqual({ min: 0, max: 0 });
  });

  it('keeps decimals on a fractional count', () => {
    expect(quantityFractionDigits(2.5, 'pcs')).toEqual({ min: 3, max: 3 });
  });

  it('keeps significant digits of tiny values', () => {
    expect(quantityFractionDigits(0.00012, 't').max).toBeGreaterThanOrEqual(6);
  });

  it('knows count units case-insensitively', () => {
    expect(isCountUnit('PCS')).toBe(true);
    expect(isCountUnit('m')).toBe(false);
  });
});
