import { beforeEach, describe, expect, it } from 'vitest';
import { COMFORT_KEY, DEFAULT_COMFORT, readComfort, writeComfort } from '../comfort';

describe('comfort options', () => {
  beforeEach(() => localStorage.clear());

  it('falls back to defaults on missing or invalid storage', () => {
    expect(readComfort()).toEqual(DEFAULT_COMFORT);
    localStorage.setItem(COMFORT_KEY, JSON.stringify({ motion: 'wild', contrast: 'high' }));
    expect(readComfort()).toEqual({ motion: 'full', contrast: 'high' });
  });

  it('persists a choice, applies it to <html> and clears storage on default', () => {
    writeComfort({ motion: 'reduced', contrast: 'high' });
    expect(readComfort()).toEqual({ motion: 'reduced', contrast: 'high' });
    expect(document.documentElement.dataset.motion).toBe('reduced');
    expect(document.documentElement.dataset.contrast).toBe('high');
    writeComfort({ ...DEFAULT_COMFORT });
    expect(localStorage.getItem(COMFORT_KEY)).toBeNull();
  });
});
