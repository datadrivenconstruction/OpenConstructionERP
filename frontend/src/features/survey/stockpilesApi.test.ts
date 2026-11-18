// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { formatTonnes, formatVariance, parseNumber, stockpileReportUrl, varianceTone } from './stockpilesApi';

describe('stockpile helpers (Riverside Yard lesson numbers)', () => {
  it('formats the course tonnes with two decimals', () => {
    expect(formatTonnes(8087.04, 'en')).toBe('8,087.04');
    expect(formatTonnes(7987.2, 'en')).toBe('7,987.20');
    expect(formatTonnes(null, 'en')).toBe('-');
  });
  it('writes the variance with its sign', () => {
    expect(formatVariance(-3.73, 'en')).toBe('-3.73 %');
    expect(formatVariance(-4.91, 'en')).toBe('-4.91 %');
    expect(formatVariance(null, 'en')).toBe('-');
  });
  it('warns beyond the tolerance and defaults to 3 %', () => {
    expect(varianceTone(-3.73, null)).toBe('warning');
    expect(varianceTone(-2.9, null)).toBe('success');
    expect(varianceTone(-3.73, 5)).toBe('success');
    expect(varianceTone(null, null)).toBe('neutral');
  });
  it('reads a decimal comma or point and refuses text', () => {
    expect(parseNumber('1,62')).toBe(1.62);
    expect(parseNumber(' 1.60 ')).toBe(1.6);
    expect(parseNumber('')).toBeNull();
    expect(parseNumber('abc')).toBeNull();
  });
  it('points the report at the survey', () => {
    expect(stockpileReportUrl('s1', 'de')).toBe('/api/v1/stockpiles/surveys/s1/report.pdf?locale=de');
  });
});
