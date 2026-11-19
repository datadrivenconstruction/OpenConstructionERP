// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { formatAngle, parseAngle, parseCoord, parseRing } from './angles';

describe('parseAngle', () => {
  it('reads DMS in the ways surveyors type it', () => {
    for (const text of ['49 06 23.4', `49°06'23.4"`, '49-06-23.4']) {
      expect(parseAngle(text, 'dms')).toBeCloseTo(49.1065, 4);
    }
    expect(parseAngle('-12-30-00', 'dms')).toBeCloseTo(-12.5, 9);
  });

  it('reads decimal degrees and gon', () => {
    expect(parseAngle('49.1065', 'deg')).toBeCloseTo(49.1065, 9);
    expect(parseAngle('54.5627', 'gon')).toBeCloseTo(49.10643, 4);
  });

  it('refuses minutes or seconds of 60 and junk', () => {
    expect(parseAngle('10 60 00', 'dms')).toBeNull();
    expect(parseAngle('abc', 'deg')).toBeNull();
    expect(parseAngle('', 'gon')).toBeNull();
  });
});

describe('formatAngle', () => {
  it('formats the COGO example bearing in every unit', () => {
    expect(formatAngle(49.10650, 'dms')).toBe(`49°06'23.4"`);
    expect(formatAngle(49.1065, 'deg')).toBe('49.106500');
    expect(formatAngle(49.1065, 'gon')).toBe('54.56278');
  });

  it('carries 59.95 seconds into the next minute', () => {
    expect(formatAngle(10 + 59 / 60 + 59.96 / 3600, 'dms')).toBe(`11°00'00.0"`);
  });
});

describe('coordinates', () => {
  it('reads E N and E N Z', () => {
    expect(parseCoord('1000.000 2000.000')).toEqual([1000, 2000]);
    expect(parseCoord('1000;2000;12.5')).toEqual([1000, 2000, 12.5]);
    expect(parseCoord('1000')).toBeNull();
  });

  it('reads a ring of three or more lines', () => {
    expect(parseRing('0 0\n50 0\n50 32\n0 28')).toEqual([[0, 0], [50, 0], [50, 32], [0, 28]]);
    expect(parseRing('0 0\n1 1')).toBeNull();
  });
});
