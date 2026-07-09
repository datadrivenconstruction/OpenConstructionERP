import { describe, it, expect } from 'vitest';
import { PX_PER_DAY, dayToX, durationToWidth } from './ganttScale';

describe('dayToX', () => {
  it('scales a day offset by PX_PER_DAY', () => {
    expect(dayToX(0)).toBe(0);
    expect(dayToX(3)).toBe(3 * PX_PER_DAY);
    expect(dayToX(13)).toBe(13 * PX_PER_DAY);
  });

  it('clamps negative days to 0', () => {
    expect(dayToX(-5)).toBe(0);
  });
});

describe('durationToWidth', () => {
  it('scales a duration by PX_PER_DAY', () => {
    expect(durationToWidth(13)).toBe(13 * PX_PER_DAY);
    expect(durationToWidth(1)).toBe(PX_PER_DAY);
  });

  it('clamps negative durations to 0', () => {
    expect(durationToWidth(-2)).toBe(0);
  });

  it('is 0 for a 0-day duration', () => {
    expect(durationToWidth(0)).toBe(0);
  });
});
