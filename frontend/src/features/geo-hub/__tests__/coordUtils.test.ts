// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Unit tests for coordUtils — DD/DMS round-trip, range validation, and
 * tolerant parsing.
 */

import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { describe, expect, it } from 'vitest';

import {
  COORD_RANGES,
  ddToDms,
  ddToDmsString,
  formatDms,
  isValidCoord,
  parseDms,
  roundCoord,
} from '../coordUtils';

describe('isValidCoord', () => {
  it('accepts values inside the lat range', () => {
    expect(isValidCoord(0, 'lat')).toBe(true);
    expect(isValidCoord(90, 'lat')).toBe(true);
    expect(isValidCoord(-90, 'lat')).toBe(true);
  });
  it('rejects values outside the lat range', () => {
    expect(isValidCoord(91, 'lat')).toBe(false);
    expect(isValidCoord(-91, 'lat')).toBe(false);
  });
  it('accepts values inside the lon range', () => {
    expect(isValidCoord(180, 'lon')).toBe(true);
    expect(isValidCoord(-180, 'lon')).toBe(true);
  });
  it('rejects NaN', () => {
    expect(isValidCoord(NaN, 'lat')).toBe(false);
  });
});

describe('ddToDms / formatDms', () => {
  it('converts a known northern lat to DMS', () => {
    const parts = ddToDms(52.52, 'lat');
    expect(parts).not.toBeNull();
    expect(parts!.degrees).toBe(52);
    expect(parts!.minutes).toBe(31);
    expect(parts!.seconds).toBeCloseTo(12, 0);
    expect(parts!.hemisphere).toBe('N');
  });
  it('converts a southern hemisphere lat', () => {
    const parts = ddToDms(-13.405, 'lon');
    expect(parts).not.toBeNull();
    expect(parts!.hemisphere).toBe('W');
  });
  it('returns null for non-finite values', () => {
    expect(ddToDms(NaN, 'lat')).toBeNull();
  });
  it('renders a DMS string with the conventional format', () => {
    const s = ddToDmsString(52.52, 'lat');
    expect(s).toMatch(/52°/);
    expect(s).toMatch(/N$/);
  });
  it('formatDms writes the seconds with the number locale decimal separator', () => {
    usePreferencesStore.setState({ numberLocale: 'de-DE' });
    try {
      const s = formatDms({ degrees: 52, minutes: 31, seconds: 12.5, hemisphere: 'N' });
      expect(s).toBe(`52° 31' 12,5" N`);
      expect(parseDms(s, 'lat')).toBeCloseTo(52 + 31 / 60 + 12.5 / 3600, 6);
    } finally {
      usePreferencesStore.setState({ numberLocale: 'auto' });
    }
  });
  it('formatDms handles 0 seconds gracefully', () => {
    const s = formatDms({
      degrees: 0,
      minutes: 0,
      seconds: 0,
      hemisphere: 'N',
    });
    expect(s).toBe('0° 0\' 0" N');
  });
});

describe('parseDms', () => {
  it('parses bare decimal degrees', () => {
    expect(parseDms('52.52', 'lat')).toBeCloseTo(52.52);
    expect(parseDms('-13.405', 'lon')).toBeCloseTo(-13.405);
  });
  it('parses ° notation', () => {
    expect(parseDms('52° 31\' 12" N', 'lat')).toBeCloseTo(52.52, 4);
  });
  it('parses with d/m/s letters', () => {
    expect(parseDms('52d 31m 12s N', 'lat')).toBeCloseTo(52.52, 4);
  });
  it('parses negative via S hemisphere', () => {
    const v = parseDms('33° 51\' 35" S', 'lat');
    expect(v).not.toBeNull();
    expect(v!).toBeLessThan(0);
  });
  it('returns null for empty / whitespace', () => {
    expect(parseDms('', 'lat')).toBeNull();
    expect(parseDms('   ', 'lat')).toBeNull();
  });
  it('returns null for out-of-range values', () => {
    expect(parseDms('200', 'lat')).toBeNull();
    expect(parseDms('-200', 'lon')).toBeNull();
  });
  it('accepts comma as decimal separator (EU locale)', () => {
    expect(parseDms('52,52', 'lat')).toBeCloseTo(52.52);
  });
});

describe('roundCoord', () => {
  it('rounds to 7 decimals by default', () => {
    expect(roundCoord(52.520000123456)).toBeCloseTo(52.5200001);
  });
  it('returns 0 for non-finite', () => {
    expect(roundCoord(NaN)).toBe(0);
  });
});

describe('COORD_RANGES', () => {
  it('exposes lat and lon ranges', () => {
    expect(COORD_RANGES.lat.min).toBe(-90);
    expect(COORD_RANGES.lon.max).toBe(180);
  });
});
