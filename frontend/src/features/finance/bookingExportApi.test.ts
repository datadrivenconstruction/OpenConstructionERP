import { describe, expect, it } from 'vitest';
import { BOOKING_CONNECTOR_TYPES, previousMonth } from './bookingExportApi';

describe('booking export helpers', () => {
  it('proposes the previous calendar month', () => {
    expect(previousMonth(new Date(2026, 10, 16))).toEqual({ from: '2026-10-01', to: '2026-10-31' });
    expect(previousMonth(new Date(2026, 0, 5))).toEqual({ from: '2025-12-01', to: '2025-12-31' });
  });

  it('treats the generic and the EXTF connectors as booking types', () => {
    expect(BOOKING_CONNECTOR_TYPES).toContain('booking_csv');
    expect(BOOKING_CONNECTOR_TYPES).toContain('datev_extf');
  });
});
