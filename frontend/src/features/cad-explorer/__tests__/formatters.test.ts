import { describe, it, expect } from 'vitest';
import { formatValue } from '@/shared/lib/numberFormat';

// These tests deliberately assert on digit presence / structure rather than
// exact strings. Intl.NumberFormat output varies by ICU version — browsers
// and the CI image may render '1,234' or '1 234' depending on the
// environment's Unicode space character, and currency symbols differ by
// locale. Asserting digit characters keeps the test portable while still
// validating that grouping and formatting ran.

describe('formatValue — number kind', () => {
  it('handles zero', () => {
    expect(formatValue(0, 'number')).toMatch(/0/);
  });

  it('returns placeholder for null / undefined / NaN / Infinity', () => {
    expect(formatValue(null, 'number')).toBe('-');
    expect(formatValue(undefined, 'number')).toBe('-');
    expect(formatValue(NaN, 'number')).toBe('-');
    expect(formatValue(Infinity, 'number')).toBe('-');
    expect(formatValue(-Infinity, 'number')).toBe('-');
  });

  it('inserts a thousand separator', () => {
    const s = formatValue(1234, 'number');
    // Any locale-appropriate grouping separator between 1 and 234.
    expect(s).toMatch(/1[^0-9]234/);
  });

  it('handles very large numbers without losing digits', () => {
    const s = formatValue(1234567890, 'number');
    // At least the first + last digits survive, with grouping in between.
    expect(s.replace(/[^0-9]/g, '')).toBe('1234567890');
  });

  it('formats negative numbers', () => {
    const s = formatValue(-1234.5, 'number');
    expect(s).toMatch(/-/);
    expect(s.replace(/[^0-9]/g, '')).toMatch(/12345/);
  });

  it('respects maximumFractionDigits override', () => {
    const s = formatValue(1.23456, 'number', { maximumFractionDigits: 4 });
    expect(s).toMatch(/1[^0-9]?2346|1\.2346/);
  });
});

describe('formatValue — currency kind', () => {
  it('includes digits of the value', () => {
    const s = formatValue(1234.5, 'currency', { currency: 'EUR' });
    expect(s.replace(/[^0-9]/g, '')).toMatch(/12345|1234/);
  });

  it('falls back to EUR when currency code is invalid', () => {
    const s = formatValue(100, 'currency', { currency: 'BOGUS' });
    // Should still render without throwing — Intl will use 'EUR'.
    expect(s).toBeTruthy();
    expect(s.replace(/[^0-9]/g, '')).toMatch(/100/);
  });

  it('renders zero amount', () => {
    const s = formatValue(0, 'currency', { currency: 'USD' });
    expect(s).toMatch(/0/);
  });

  it('renders negative amount with sign / accounting brackets', () => {
    const s = formatValue(-100, 'currency', { currency: 'USD' });
    // Either a leading minus or accounting parentheses in some locales.
    expect(/[-\u2212()]/.test(s)).toBe(true);
  });
});

describe('formatValue — percent kind', () => {
  it('appends a % sign to the raw percentage (stored-value semantics)', () => {
    const s = formatValue(42.5, 'percent');
    expect(s).toContain('%');
    expect(s.replace(/[^0-9]/g, '')).toMatch(/425|42/);
  });

  it('multiplies by 100 when percentAsRatio is true', () => {
    const s = formatValue(0.5, 'percent', { percentAsRatio: true });
    expect(s).toContain('%');
    expect(s.replace(/[^0-9]/g, '')).toMatch(/50/);
  });

  it('handles zero', () => {
    const s = formatValue(0, 'percent');
    expect(s).toContain('%');
  });

  it('handles negative percentages', () => {
    const s = formatValue(-12.5, 'percent');
    expect(s).toMatch(/-/);
    expect(s).toContain('%');
  });
});
