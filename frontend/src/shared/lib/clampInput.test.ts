import { describe, it, expect } from 'vitest';
import { clampInput } from './clampInput';

describe('clampInput', () => {
  it('clamps negatives to the minimum', () => {
    expect(clampInput('-5', 0)).toBe(0);
    expect(clampInput('-0.4', 0, 1)).toBe(0);
  });
  it('clamps probability above 1', () => {
    expect(clampInput('7', 0, 1)).toBe(1);
  });
  it('clamps days to the ceiling and truncates', () => {
    expect(clampInput('99999', 0, 36500, true)).toBe(36500);
    expect(clampInput('12.9', 0, 36500, true)).toBe(12);
  });
  it('keeps valid values and falls back to min on empty', () => {
    expect(clampInput('0.25', 0, 1)).toBe(0.25);
    expect(clampInput('', 0, 1)).toBe(0);
  });
});
