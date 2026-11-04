import { describe, expect, it } from 'vitest';
import { parseApplyQuantity } from '../applyQuantity';

describe('parseApplyQuantity', () => {
  it('accepts positive finite numbers', () => {
    expect(parseApplyQuantity('2.5')).toBe(2.5);
  });
  it.each(['', ' ', '0', '-3', 'abc', 'Infinity', 'NaN'])('rejects %j instead of falling back to 1', (raw) => {
    expect(parseApplyQuantity(raw)).toBeNull();
  });
});
