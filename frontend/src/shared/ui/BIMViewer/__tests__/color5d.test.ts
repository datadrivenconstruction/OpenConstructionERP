import { describe, expect, it } from 'vitest';
import {
  colorAtStop,
  colorForRate,
  normalizeRate,
  DEFAULT_5D_GRADIENT,
  NO_LINK_COLOR,
} from '../color5d';

describe('normalizeRate', () => {
  it('maps rate=min to 0 and rate=max to 1', () => {
    expect(normalizeRate(10, 10, 100)).toBe(0);
    expect(normalizeRate(100, 10, 100)).toBe(1);
  });

  it('maps a midpoint rate to 0.5', () => {
    expect(normalizeRate(55, 10, 100)).toBeCloseTo(0.5, 3);
  });

  it('clamps below-range rates to 0', () => {
    expect(normalizeRate(5, 10, 100)).toBe(0);
  });

  it('clamps above-range rates to 1', () => {
    expect(normalizeRate(150, 10, 100)).toBe(1);
  });

  it('returns null for null / undefined / NaN / Infinity inputs', () => {
    expect(normalizeRate(null, 0, 100)).toBeNull();
    expect(normalizeRate(undefined, 0, 100)).toBeNull();
    expect(normalizeRate(NaN, 0, 100)).toBeNull();
    expect(normalizeRate(Infinity, 0, 100)).toBeNull();
  });

  it('returns 0.5 on a degenerate range (min === max) — safe middle colour', () => {
    expect(normalizeRate(42, 42, 42)).toBe(0.5);
  });

  it('returns null when the range is inverted (max < min)', () => {
    expect(normalizeRate(5, 10, 1)).toBeNull();
  });
});

describe('colorAtStop — gradient interpolation', () => {
  it('returns the exact stop colour when t matches a stop', () => {
    expect(colorAtStop(0)).toBe(DEFAULT_5D_GRADIENT[0]!.hex);
    expect(colorAtStop(0.5)).toBe(DEFAULT_5D_GRADIENT[1]!.hex);
    expect(colorAtStop(1)).toBe(DEFAULT_5D_GRADIENT[2]!.hex);
  });

  it('produces a blue-ish colour at the low end', () => {
    // #0071e3 is heavy in blue — low t should reflect that.
    const hex = colorAtStop(0.05);
    const b = parseInt(hex.slice(5, 7), 16);
    const r = parseInt(hex.slice(1, 3), 16);
    expect(b).toBeGreaterThan(r);
  });

  it('produces a red-ish colour at the high end', () => {
    // #ef4444 — should have R >> G and R >> B.
    const hex = colorAtStop(0.95);
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    expect(r).toBeGreaterThan(g);
    expect(r).toBeGreaterThan(b);
  });

  it('produces an amber-ish colour in the middle', () => {
    const hex = colorAtStop(0.5);
    // The middle stop itself is #f59e0b — so at t=0.5 we should hit that exactly.
    expect(hex).toBe('#f59e0b');
  });

  it('clamps t < 0 to the first stop', () => {
    expect(colorAtStop(-0.5)).toBe(DEFAULT_5D_GRADIENT[0]!.hex);
  });

  it('clamps t > 1 to the last stop', () => {
    expect(colorAtStop(2)).toBe(DEFAULT_5D_GRADIENT[DEFAULT_5D_GRADIENT.length - 1]!.hex);
  });

  it('handles an empty / single-stop gradient gracefully', () => {
    expect(colorAtStop(0.5, [])).toBe(NO_LINK_COLOR);
    expect(colorAtStop(0.5, [{ t: 0, hex: '#123456' }])).toBe('#123456');
  });
});

describe('colorForRate — end-to-end rate → { color, hasLink }', () => {
  it('returns the NO_LINK_COLOR and hasLink=false when rate is null', () => {
    const { color, hasLink } = colorForRate(null, 0, 100);
    expect(color).toBe(NO_LINK_COLOR);
    expect(hasLink).toBe(false);
  });

  it('returns a gradient colour and hasLink=true for a valid rate', () => {
    const { color, hasLink } = colorForRate(50, 0, 100);
    expect(hasLink).toBe(true);
    expect(color).toMatch(/^#[0-9a-f]{6}$/i);
    expect(color).not.toBe(NO_LINK_COLOR);
  });

  it('low rate renders blue-ish (low r, high b)', () => {
    const { color } = colorForRate(5, 0, 100);
    const r = parseInt(color.slice(1, 3), 16);
    const b = parseInt(color.slice(5, 7), 16);
    expect(b).toBeGreaterThan(r);
  });

  it('high rate renders red-ish (high r, low b)', () => {
    const { color } = colorForRate(95, 0, 100);
    const r = parseInt(color.slice(1, 3), 16);
    const b = parseInt(color.slice(5, 7), 16);
    expect(r).toBeGreaterThan(b);
  });

  it('treats rate===min as the low end of the gradient', () => {
    const { color } = colorForRate(10, 10, 100);
    expect(color).toBe(DEFAULT_5D_GRADIENT[0]!.hex);
  });

  it('treats rate===max as the high end of the gradient', () => {
    const { color } = colorForRate(100, 10, 100);
    expect(color).toBe(DEFAULT_5D_GRADIENT[2]!.hex);
  });

  it('picks the middle stop when the range is degenerate', () => {
    const { color, hasLink } = colorForRate(42, 42, 42);
    expect(hasLink).toBe(true);
    expect(color).toBe('#f59e0b'); // middle of default gradient
  });
});
