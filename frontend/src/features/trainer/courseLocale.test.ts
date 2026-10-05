// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';

import {
  baseLanguage,
  courseDir,
  courseLanguageName,
  courseLocaleOf,
  numberSeparators,
  parseCourseNumber,
  sameLanguage,
} from './courseLocale';

describe('courseLocaleOf', () => {
  it('uses course.locale when it is a valid tag', () => {
    expect(courseLocaleOf({ locale: 'en-GB', language: 'en', country: 'GB' })).toBe('en-GB');
    expect(courseLocaleOf({ locale: 'de-de', language: 'de', country: 'DE' })).toBe('de-DE');
  });

  it('falls back to language-country, then the language', () => {
    expect(courseLocaleOf({ locale: '', language: 'en', country: 'GB' })).toBe('en-GB');
    expect(courseLocaleOf({ locale: 'not a tag', language: 'fr', country: 'FR' })).toBe('fr-FR');
    expect(courseLocaleOf({ locale: '', language: 'fr', country: '!!' })).toBe('fr');
  });
});

describe('language helpers', () => {
  it('reads the base language and the direction', () => {
    expect(baseLanguage('en-GB')).toBe('en');
    expect(courseDir('ar-SA')).toBe('rtl');
    expect(courseDir('he')).toBe('rtl');
    expect(courseDir('de-DE')).toBe('ltr');
  });

  it('compares languages, not regions', () => {
    expect(sameLanguage('en-GB', 'en')).toBe(true);
    expect(sameLanguage('en-US', 'en-GB')).toBe(true);
    expect(sameLanguage('de-DE', 'en')).toBe(false);
  });

  it('names the course language in the UI language', () => {
    expect(courseLanguageName('de-DE', 'en')).toBe('German');
    expect(courseLanguageName('fr-FR', 'de')).toBe('Französisch');
  });
});

describe('numberSeparators', () => {
  it('reads separators from Intl', () => {
    expect(numberSeparators('en-GB')).toMatchObject({ group: ',', decimal: '.', middleGroupSize: 3, digits: null });
    expect(numberSeparators('de-DE')).toMatchObject({ group: '.', decimal: ',' });
    expect(numberSeparators('en-IN').middleGroupSize).toBe(2);
  });
});

describe('parseCourseNumber', () => {
  it('reads each locale under its own separators', () => {
    expect(parseCourseNumber('3,581,310.00', 'en-GB')).toBe('3581310.00');
    expect(parseCourseNumber('3.581.310,00', 'de-DE')).toBe('3581310.00');
    expect(parseCourseNumber('3581310,00', 'de-DE')).toBe('3581310.00');
    expect(parseCourseNumber('3581310.00', 'en-US')).toBe('3581310.00');
  });

  it('refuses grouping that does not fit the locale instead of guessing', () => {
    expect(parseCourseNumber('3581310.00', 'de-DE')).toBeNull();
    expect(parseCourseNumber('3,581,310.00', 'de-DE')).toBeNull();
    expect(parseCourseNumber('3.581.310,00', 'en-GB')).toBeNull();
    expect(parseCourseNumber('35,81,310', 'en-GB')).toBeNull();
    expect(parseCourseNumber('1,5', 'en-GB')).toBeNull();
    expect(parseCourseNumber('1,2345', 'en-GB')).toBeNull();
  });

  it('accepts any space as a group separator, including the French narrow one', () => {
    const fr = new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2 }).format(3581310);
    expect(parseCourseNumber(fr, 'fr-FR')).toBe('3581310.00');
    expect(parseCourseNumber('3 581 310,00', 'fr-FR')).toBe('3581310.00');
    expect(parseCourseNumber('3 581 310.00', 'en-GB')).toBe('3581310.00');
  });

  it('reads Swiss apostrophes and Indian grouping', () => {
    const ch = new Intl.NumberFormat('de-CH', { minimumFractionDigits: 2 }).format(3581310);
    expect(parseCourseNumber(ch, 'de-CH')).toBe('3581310.00');
    expect(parseCourseNumber('3\u2019581\u2019310.00', 'de-CH')).toBe('3581310.00');
    expect(parseCourseNumber('35,81,310.50', 'en-IN')).toBe('3581310.50');
  });

  it('reads native digits', () => {
    const ar = new Intl.NumberFormat('ar-EG', { minimumFractionDigits: 2 }).format(1234.5);
    expect(parseCourseNumber(ar, 'ar-EG')).toBe('1234.50');
  });

  it('strips currency and percent decorations', () => {
    expect(parseCourseNumber('£3,581,310.00', 'en-GB')).toBe('3581310.00');
    expect(parseCourseNumber('3.581.310,00 €', 'de-DE')).toBe('3581310.00');
    expect(parseCourseNumber('GBP 1,000', 'en-GB')).toBe('1000');
    expect(parseCourseNumber('12,5 %', 'de-DE')).toBe('12.5');
    expect(parseCourseNumber('5%', 'en-GB')).toBe('5');
  });

  it('keeps the sign and the decimals as typed, never through a float', () => {
    expect(parseCourseNumber('-18,810.00', 'en-GB')).toBe('-18810.00');
    expect(parseCourseNumber('\u221218.810,00', 'de-DE')).toBe('-18810.00');
    expect(parseCourseNumber('-£12', 'en-GB')).toBe('-12');
    expect(parseCourseNumber('+7', 'en-GB')).toBe('7');
    expect(parseCourseNumber('0.1', 'en-GB')).toBe('0.1');
    expect(parseCourseNumber('12345678901234567.89', 'en-GB')).toBe('12345678901234567.89');
    expect(parseCourseNumber('007', 'en-GB')).toBe('7');
    expect(parseCourseNumber('.5', 'en-GB')).toBe('0.5');
    expect(parseCourseNumber('-0', 'en-GB')).toBe('0');
  });

  it('refuses what is not a number', () => {
    for (const bad of ['', '   ', 'abc', '12a', '1.2.3', '1.', '--1', '£', '%', '1e5', '0x10']) {
      expect(parseCourseNumber(bad, 'en-GB')).toBeNull();
    }
  });
});
