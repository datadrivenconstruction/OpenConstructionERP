import { describe, it, expect } from 'vitest';
import { fmtCur } from './RiskRegisterPage';

describe('risk register money', () => {
  it('shows a bare number when the risk has no currency instead of guessing EUR', () => {
    const out = fmtCur(12500, '');
    expect(out).not.toMatch(/€|EUR/);
    expect(out.replace(/\D/g, '')).toBe('12500');
  });
  it('keeps the stored currency when there is one', () => {
    expect(fmtCur(12500, 'USD')).toMatch(/\$|USD/);
  });
});
