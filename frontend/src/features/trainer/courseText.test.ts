// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  formatCourseDate,
  formatCourseMoney,
  formatCourseNumber,
  formatCoursePercent,
  formatCourseValue,
  parseIsoDate,
  renderCourseText,
} from './courseText';

// Intl output contains U+00A0 and U+202F in some locales; compare with
// ordinary spaces so the expectations stay readable.
const plain = (s: string) => s.replace(/[\u00a0\u202f]/g, ' ');

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('parseIsoDate', () => {
  it('accepts real calendar dates only', () => {
    expect(parseIsoDate('2026-09-01')?.toISOString()).toBe('2026-09-01T00:00:00.000Z');
    expect(parseIsoDate('2028-02-29')).not.toBeNull();
    expect(parseIsoDate('2026-02-31')).toBeNull();
    expect(parseIsoDate('2026-13-01')).toBeNull();
    expect(parseIsoDate('2026-9-1')).toBeNull();
    expect(parseIsoDate('2026-09-01T00:00:00Z')).toBeNull();
  });
});

describe('formatCourseDate', () => {
  it('writes the date in words for the four course locales', () => {
    expect(formatCourseDate('2026-09-01', 'en-GB')).toBe('1 September 2026');
    expect(formatCourseDate('2026-09-01', 'en-US')).toBe('September 1, 2026');
    expect(formatCourseDate('2026-09-01', 'de-DE')).toBe('1. September 2026');
    expect(formatCourseDate('2026-09-01', 'fr-FR')).toBe('1 septembre 2026');
  });

  it('keeps the calendar day in a western time zone (no off-by-one)', () => {
    const before = process.env.TZ;
    process.env.TZ = 'America/Los_Angeles';
    try {
      expect(formatCourseDate('2026-01-01', 'en-US')).toBe('January 1, 2026');
      expect(formatCourseDate('2026-12-31', 'en-GB')).toBe('31 December 2026');
    } finally {
      if (before === undefined) delete process.env.TZ;
      else process.env.TZ = before;
    }
  });

  it('returns a non-date unchanged', () => {
    expect(formatCourseDate('2026-02-31', 'en-GB')).toBe('2026-02-31');
    expect(formatCourseDate('soon', 'en-GB')).toBe('soon');
  });
});

describe('renderCourseText', () => {
  it('replaces each standalone ISO date', () => {
    expect(renderCourseText('Valuation date 2026-09-30, paid by 2026-10-28.', 'en-GB')).toBe(
      'Valuation date 30 September 2026, paid by 28 October 2026.',
    );
    expect(renderCourseText('Stichtag (2026-09-30)', 'de-DE')).toBe('Stichtag (30. September 2026)');
  });

  it('leaves ids, timestamps and impossible dates alone', () => {
    expect(renderCourseText('Invoice INV-2026-09-01 issued', 'en-GB')).toBe('Invoice INV-2026-09-01 issued');
    expect(renderCourseText('at 2026-09-01T10:00Z', 'en-GB')).toBe('at 2026-09-01T10:00Z');
    expect(renderCourseText('on 2026-02-31', 'en-GB')).toBe('on 2026-02-31');
    expect(renderCourseText('', 'en-GB')).toBe('');
  });
});

describe('numbers, percents and money in the course locale', () => {
  it('formats numbers with the decimals they were sent with', () => {
    expect(formatCourseNumber('1234.5', 'en-GB')).toBe('1,234.5');
    expect(formatCourseNumber('1234.50', 'de-DE')).toBe('1.234,50');
    expect(plain(formatCourseNumber('1234567', 'fr-FR'))).toBe('1 234 567');
    expect(formatCourseNumber('n/a', 'en-GB')).toBe('n/a');
  });

  it('formats a percent value without multiplying it by 100', () => {
    expect(formatCoursePercent('5.00', 'en-GB')).toBe('5%');
    expect(plain(formatCoursePercent('12.50', 'de-DE'))).toBe('12,5 %');
    expect(plain(formatCoursePercent('2.25', 'fr-FR'))).toBe('2,25 %');
  });

  it('uses the course currency and locale, not the UI language', () => {
    expect(formatCourseMoney('3581310.00', 'GBP', 'en-GB')).toBe('£3,581,310.00');
    expect(plain(formatCourseMoney('3581310.00', 'EUR', 'de-DE'))).toBe('3.581.310,00 €');
    expect(plain(formatCourseMoney('-18810', 'EUR', 'fr-FR'))).toBe('-18 810,00 €');
    expect(formatCourseMoney('n/a', 'GBP', 'en-GB')).toBe('n/a');
  });
});

describe('formatCourseValue', () => {
  const ctx = { locale: 'en-GB', currency: 'GBP' };

  it('dispatches on the value kind', () => {
    expect(formatCourseValue('34489.48', 'money', ctx)).toBe('£34,489.48');
    expect(formatCourseValue('100', 'money', ctx, 'EUR')).toBe('€100.00');
    expect(formatCourseValue('5.00', 'percent', ctx)).toBe('5%');
    expect(formatCourseValue('12', 'number', ctx)).toBe('12');
    expect(formatCourseValue('2026-09-01', 'date', ctx)).toBe('1 September 2026');
    expect(formatCourseValue('due 2026-09-01', 'text', ctx)).toBe('due 1 September 2026');
    expect(formatCourseValue(null, 'money', ctx)).toBe('');
  });
});
