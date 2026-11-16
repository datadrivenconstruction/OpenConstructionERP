import { describe, expect, it } from 'vitest';
import { lastCompletedWeek } from './payrollApi';
import { HOUR_TYPES } from './api';

describe('payroll export helpers', () => {
  it('proposes the last completed Monday to Sunday week', () => {
    // Wednesday 18 Nov 2026 -> week 9 to 15 Nov
    expect(lastCompletedWeek(new Date(2026, 10, 18))).toEqual({ from: '2026-11-09', to: '2026-11-15' });
    // A Monday proposes the week that ended yesterday
    expect(lastCompletedWeek(new Date(2026, 10, 16))).toEqual({ from: '2026-11-09', to: '2026-11-15' });
  });

  it('offers regular first and the seven hour types the backend accepts', () => {
    expect(HOUR_TYPES[0]).toBe('regular');
    expect(HOUR_TYPES).toHaveLength(7);
  });
});
