// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Telematics formatting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ helper tests.
import { describe, expect, it } from 'vitest';
import { barWidth, hoursShares, idleTone, importKindFor, lastDaysWindow, toNumber } from './telematicsFormat';

describe('lastDaysWindow', () => {
  it('covers 14 calendar days ending today, inclusive', () => {
    expect(lastDaysWindow(14, new Date(2026, 9, 26))).toEqual({ date_from: '2026-10-13', date_to: '2026-10-26' });
  });
  it('crosses a month boundary', () => {
    expect(lastDaysWindow(3, new Date(2026, 10, 1))).toEqual({ date_from: '2026-10-30', date_to: '2026-11-01' });
  });
});

describe('importKindFor', () => {
  it('routes XML and JSON to AEMP and CSV to the CSV importer', () => {
    expect(importKindFor('fleet.XML')).toBe('aemp');
    expect(importKindFor('fleet.json')).toBe('aemp');
    expect(importKindFor('fleet.csv')).toBe('csv');
    expect(importKindFor('fleet.xlsx')).toBeNull();
  });
});

describe('numbers', () => {
  it('reads Decimal strings and survives junk', () => {
    expect(toNumber('12.50')).toBe(12.5);
    expect(toNumber(null)).toBe(0);
    expect(toNumber('abc')).toBe(0);
  });
  it('clamps bar widths', () => {
    expect(barWidth('140')).toBe(100);
    expect(barWidth(-5)).toBe(0);
  });
  it('flags a high idle share', () => {
    expect(idleTone('45.0')).toContain('warning');
    expect(idleTone('10')).toContain('primary');
  });
  it('splits hours into shares of their sum', () => {
    const s = hoursShares({ worked_hours: '6', idle_hours: '2', off_hours: '2' });
    expect(s.worked).toBeCloseTo(60);
    expect(s.idle).toBeCloseTo(20);
    expect(hoursShares({ worked_hours: '0', idle_hours: '0', off_hours: '0' })).toEqual({ worked: 0, idle: 0, off: 0 });
  });
});
