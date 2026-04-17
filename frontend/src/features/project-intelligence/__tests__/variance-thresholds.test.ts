import { describe, it, expect } from 'vitest';
import {
  classifyVariance,
  VARIANCE_AMBER_THRESHOLD,
  VARIANCE_GREEN_THRESHOLD,
} from '../components/variance-thresholds';

describe('classifyVariance — traffic-light thresholds (RFC 25)', () => {
  it('uses the documented thresholds', () => {
    expect(VARIANCE_GREEN_THRESHOLD).toBe(3.0);
    expect(VARIANCE_AMBER_THRESHOLD).toBe(5.0);
  });

  it('returns green inside ±3%', () => {
    expect(classifyVariance(0)).toBe('green');
    expect(classifyVariance(2.9)).toBe('green');
    expect(classifyVariance(-3.0)).toBe('green');
    expect(classifyVariance(3.0)).toBe('green');
  });

  it('returns amber between ±3% and ±5%', () => {
    expect(classifyVariance(3.01)).toBe('amber');
    expect(classifyVariance(-4.5)).toBe('amber');
    expect(classifyVariance(5.0)).toBe('amber');
  });

  it('returns red outside ±5%', () => {
    expect(classifyVariance(5.1)).toBe('red');
    expect(classifyVariance(-7.5)).toBe('red');
    expect(classifyVariance(100)).toBe('red');
  });
});
