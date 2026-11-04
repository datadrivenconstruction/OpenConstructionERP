import { describe, it, expect } from 'vitest';
import { clampDaysLost, DAYS_LOST_MAX } from './SafetyPage';

describe('incident days lost input', () => {
  it('caps values above the API bound', () => {
    expect(clampDaysLost('9999999999')).toBe(DAYS_LOST_MAX);
  });
  it('keeps normal values and floors junk at zero', () => {
    expect(clampDaysLost('12')).toBe(12);
    expect(clampDaysLost('-3')).toBe(0);
    expect(clampDaysLost('')).toBe(0);
  });
});
