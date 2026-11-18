import { describe, expect, it } from 'vitest';
import { levyAdjusted } from './markupLevy';

describe('levyAdjusted', () => {
  const levy = { threshold_amount: '3000000', not_compounded: true };

  it('charges the whole base above the threshold and does not compound', () => {
    expect(levyAdjusted(levy, 50_000_000, 250_000)).toEqual({ amount: 250_000, compounds: false });
  });

  it('charges nothing at or below the threshold', () => {
    expect(levyAdjusted(levy, 3_000_000, 15_000).amount).toBe(0);
  });

  it('leaves an ordinary line alone', () => {
    expect(levyAdjusted({}, 100, 5)).toEqual({ amount: 5, compounds: true });
    expect(levyAdjusted(undefined, 100, 5)).toEqual({ amount: 5, compounds: true });
  });
});
