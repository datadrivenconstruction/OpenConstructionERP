import { describe, expect, it } from 'vitest';
import { barPercent } from '../ProjectDetailPage';

describe('barPercent', () => {
  it('keeps an in-range value', () => {
    expect(barPercent(42.5)).toBe(42.5);
  });
  it('clamps above 100 and below 0', () => {
    expect(barPercent(250)).toBe(100);
    expect(barPercent(-5)).toBe(0);
  });
  it('turns NaN and Infinity into 0 so a bar never falls back to full width', () => {
    expect(barPercent(Number.NaN)).toBe(0);
    expect(barPercent(Number.POSITIVE_INFINITY)).toBe(0);
  });
});
