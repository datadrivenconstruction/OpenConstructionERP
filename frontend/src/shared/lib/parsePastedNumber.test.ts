import { describe, it, expect } from 'vitest';
import { parsePastedNumber, resolveAmbiguousSeparator, localeUsesDecimalComma } from './parseDecimal';

const v = (raw: string, locale: string | null = 'fr-FR') => parsePastedNumber(raw, locale).value;

describe('parsePastedNumber - market spellings', () => {
  it.each([
    ['1 250,00', 1250],
    ['1 250.00', 1250],
    ['0,250', 0.25],
    ['1.234,56', 1234.56],
    ['1,234.56', 1234.56],
    ['1\u00A0250,00', 1250],
    ['1\u202F250,00', 1250],
    ["12'500.50", 12500.5],
    ['12\u2019500.50', 12500.5],
    ['1 250,00 €', 1250],
    ['€ 1.234,56', 1234.56],
    ['2,625 m3', 2.625],
    ['12,5 m²', 12.5],
    ['CHF 1\'234.50', 1234.5],
  ])('%s -> %s', (raw, expected) => {
    expect(v(raw)).toBe(expected);
  });

  it('empty or text-only is no number', () => {
    expect(v('')).toBeNull();
    expect(v('abc')).toBeNull();
  });
});

describe('ambiguous lone separator before three digits', () => {
  it.each([
    ['fr-FR', '1,250', 1.25],
    ['fr-FR', '1.250', 1250],
    ['de-DE', '1,250', 1.25],
    ['de-DE', '1.250', 1250],
    ['en-US', '1,250', 1250],
    ['en-US', '1.250', 1.25],
    ['en-GB', '1,250', 1250],
    ['de-CH', '1.250', 1.25],
    ['de-CH', '1,250', 1250],
  ])('%s reads %s as %s', (locale, raw, expected) => {
    const r = parsePastedNumber(raw, locale);
    expect(r.value).toBe(expected);
    expect(r.ambiguous).toBe(false);
  });

  it('without a locale the cell is flagged for review', () => {
    expect(parsePastedNumber('1,250', null).ambiguous).toBe(true);
    expect(parsePastedNumber('1,25', null).ambiguous).toBe(false);
    expect(parsePastedNumber('1,250.00', null).ambiguous).toBe(false);
  });

  it('only the ambiguous shape is decided', () => {
    expect(resolveAmbiguousSeparator('12,50', 'fr-FR')).toBeNull();
    expect(resolveAmbiguousSeparator('0,250', 'fr-FR')).toBeNull();
    expect(resolveAmbiguousSeparator('-1,250', 'fr-FR')).toBe('-1.250');
  });

  it('knows which locales write a decimal comma', () => {
    expect(localeUsesDecimalComma('fr-FR')).toBe(true);
    expect(localeUsesDecimalComma('en-US')).toBe(false);
    expect(localeUsesDecimalComma('de-CH')).toBe(false);
  });
});

describe('decimalMarkEvidence', () => {
  it.each([
    ['1.234,56', ','],
    ['1,234.56', '.'],
    ['12,5', ','],
    ['0,250', ','],
    ['12.50', '.'],
    ['1.234.567', ','],
    ['1,250', null],
    ['1250', null],
  ])('%s proves %s', async (raw, mark) => {
    const { decimalMarkEvidence } = await import('./parseDecimal');
    expect(decimalMarkEvidence(raw)).toBe(mark);
  });
});
