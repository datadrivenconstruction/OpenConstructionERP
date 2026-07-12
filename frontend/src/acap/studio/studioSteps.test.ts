import { describe, it, expect } from 'vitest';
import {
  STEP_COUNT,
  STEP_TITLES,
  deriveStepAvailability,
} from './studioSteps';

describe('studioSteps', () => {
  it('exposes 7 steps with Indonesian titles', () => {
    expect(STEP_COUNT).toBe(7);
    expect(STEP_TITLES).toEqual([
      'Upload Gambar',
      'AI Extract',
      'Konfirmasi',
      'RAB',
      'Timeline',
      '3D',
      'Interior',
    ]);
  });

  it('limits maxStep to 3 (Upload/Extract/Konfirmasi) when there is no saved layout', () => {
    expect(deriveStepAvailability({ hasLayout: false }).maxStep).toBe(3);
  });

  it('lifts maxStep to 7 once a layout is saved (all steps reachable)', () => {
    expect(deriveStepAvailability({ hasLayout: true }).maxStep).toBe(7);
  });
});