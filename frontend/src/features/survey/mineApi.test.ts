// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { currentMonth, formatPct, formatSigned, formatTonnes, outsideBand, parseNumber, periodReportUrl, periodTitle } from './mineApi';

describe('mine survey helpers (Riverside Yard lesson numbers)', () => {
  it('formats the course percentages and tonnes', () => {
    expect(formatPct(94.96, 'en')).toBe('94.96 %');
    expect(formatSigned(4.47, 'en')).toBe('+4.47 %');
    expect(formatSigned(-2.1, 'en')).toBe('-2.10 %');
    expect(formatTonnes(23740, 'en')).toBe('23,740.00');
    expect(formatTonnes(24800, 'en')).toBe('24,800.00');
    expect(formatPct(null, 'en')).toBe('-');
  });
  it('judges the 95-105 band and stays silent without one', () => {
    expect(outsideBand(94.96, 95, 105)).toBe(true);
    expect(outsideBand(95, 95, 105)).toBe(false);
    expect(outsideBand(105, 95, 105)).toBe(false);
    expect(outsideBand(94.96, null, null)).toBeNull();
    expect(outsideBand(null, 95, 105)).toBeNull();
  });
  it('reads a decimal comma or point and refuses text', () => {
    expect(parseNumber('2,00')).toBe(2);
    expect(parseNumber(' 3 ')).toBe(3);
    expect(parseNumber('')).toBeNull();
    expect(parseNumber('x')).toBeNull();
  });
  it('names the period like the course', () => {
    expect(periodTitle('2026-10', 'en')).toBe('Oct 2026');
    expect(periodTitle('bad', 'en')).toBe('bad');
    expect(currentMonth(new Date(2026, 9, 5))).toBe('2026-10');
  });
  it('points the report at the period', () => {
    expect(periodReportUrl('p1', 'de')).toBe('/api/v1/mine-survey/periods/p1/report.pdf?locale=de');
  });
});
