// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { parseReadingsCsv, parseTime, validReadings } from './readingsCsv';
import { customDefinitionError, outsideLimits } from './sensorData';

describe('parseReadingsCsv', () => {
  it('reads time,value,note lines and drops a header', () => {
    const rows = parseReadingsCsv('time,value,note\n2026-11-02T08:00Z,42.5,Meter check\n2026-11-02 09:00Z,40\n');
    expect(rows).toHaveLength(2);
    expect(rows[0]!).toMatchObject({ line: 2, error: null });
    expect(rows[0]!.reading).toEqual({ recorded_at: '2026-11-02T08:00:00.000Z', value: 42.5, note: 'Meter check' });
    expect(rows[1]!.reading?.value).toBe(40);
  });

  it('accepts a semicolon with a decimal comma', () => {
    const [row] = parseReadingsCsv('2026-11-02T08:00Z;12,5');
    expect(row!.reading?.value).toBe(12.5);
  });

  it('flags bad times, bad values and repeated times', () => {
    const rows = parseReadingsCsv('2026-11-02T08:00Z,1\nyesterday,2\n2026-11-02T09:00Z,abc\n2026-11-02T08:00Z,3');
    expect(rows.map((r) => r.error)).toEqual([null, 'bad_time', 'bad_value', 'duplicate_time']);
    expect(validReadings(rows)).toHaveLength(1);
  });

  it('parses a time without a zone as local time', () => {
    expect(parseTime('2026-11-02 08:00')).toBe(new Date('2026-11-02T08:00').toISOString());
    expect(parseTime('02.11.2026 08:00')).toBeNull();
  });
});

describe('limits', () => {
  it('is outside above the upper and below the lower limit', () => {
    expect(outsideLimits(61, '60', '18')).toBe(true);
    expect(outsideLimits(12, '60', '18')).toBe(true);
    expect(outsideLimits(30, '60', '18')).toBe(false);
    expect(outsideLimits(5, null, null)).toBe(false);
  });

  it('checks a custom sensor definition', () => {
    expect(customDefinitionError({ unit: '', upper: '5', lower: '', recordOnly: false })).toBe('unit_required');
    expect(customDefinitionError({ unit: 'kN', upper: '5', lower: '5', recordOnly: false })).toBe('lower_not_below_upper');
    expect(customDefinitionError({ unit: 'kN', upper: '', lower: '', recordOnly: false })).toBe('limit_or_record_only');
    expect(customDefinitionError({ unit: 'kN', upper: '', lower: '', recordOnly: true })).toBeNull();
  });
});
