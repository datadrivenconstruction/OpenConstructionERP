// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Unit tests for the shared currency-catalogue helpers used by the cost
 * catalog, assembly create, and regional-default currency pickers.
 *
 * The contract under test:
 *   - `normalizeCurrencyCode` cleans free-text the same way the money
 *     formatter does before rendering a symbol (trim inner whitespace,
 *     upper-case) WITHOUT rejecting non-ISO input (the backend column is
 *     free-form `str`).
 *   - `isValidCurrencyCode` reports the ISO-4217 shape (3 ascii letters)
 *     so the picker can show a soft hint, mirroring money.ts.
 *   - The `__custom__` sentinel is excluded from the selectable code set.
 */
import { describe, it, expect } from 'vitest';
import {
  normalizeCurrencyCode,
  isValidCurrencyCode,
  CURRENCY_CODES,
  CUSTOM_CURRENCY_SENTINEL,
  lookupCountryDefault,
} from './currencyGroups';
import { COUNTRIES } from '@/shared/lib/countries';

describe('normalizeCurrencyCode', () => {
  it('upper-cases lower/mixed-case input', () => {
    expect(normalizeCurrencyCode('usd')).toBe('USD');
    expect(normalizeCurrencyCode('Eur')).toBe('EUR');
    expect(normalizeCurrencyCode('xaf')).toBe('XAF');
  });

  it('strips surrounding and inner whitespace', () => {
    expect(normalizeCurrencyCode('  usd ')).toBe('USD');
    expect(normalizeCurrencyCode('u s d')).toBe('USD');
    expect(normalizeCurrencyCode('\tGBP\n')).toBe('GBP');
  });

  it('does NOT hard-reject non-ISO codes (backend is free-form)', () => {
    // A 4-letter or numeric code is cleaned, not dropped - the caller decides
    // whether to surface a hint via isValidCurrencyCode.
    expect(normalizeCurrencyCode('usdt')).toBe('USDT');
    expect(normalizeCurrencyCode('bt c')).toBe('BTC');
  });

  it('returns empty string for empty/whitespace-only input', () => {
    expect(normalizeCurrencyCode('')).toBe('');
    expect(normalizeCurrencyCode('   ')).toBe('');
  });
});

describe('isValidCurrencyCode', () => {
  it('accepts a 3-letter code regardless of incoming case/spacing', () => {
    expect(isValidCurrencyCode('USD')).toBe(true);
    expect(isValidCurrencyCode('eur')).toBe(true);
    expect(isValidCurrencyCode('  xaf ')).toBe(true);
    expect(isValidCurrencyCode('x o f')).toBe(true);
  });

  it('rejects codes that are not exactly 3 letters', () => {
    expect(isValidCurrencyCode('US')).toBe(false);
    expect(isValidCurrencyCode('USDT')).toBe(false);
    expect(isValidCurrencyCode('US1')).toBe(false);
    expect(isValidCurrencyCode('')).toBe(false);
    expect(isValidCurrencyCode('123')).toBe(false);
  });
});

describe('CURRENCY_CODES', () => {
  it('contains common ISO codes and excludes the custom sentinel', () => {
    expect(CURRENCY_CODES.has('EUR')).toBe(true);
    expect(CURRENCY_CODES.has('USD')).toBe(true);
    expect(CURRENCY_CODES.has(CUSTOM_CURRENCY_SENTINEL)).toBe(false);
  });
});

describe('Croatia', () => {
  it('does not offer the kuna for a new project, the euro replaced it on 2023-01-01', () => {
    expect(CURRENCY_CODES.has('HRK')).toBe(false);
  });

  it('defaults a Croatian project to the Croatia region and the euro', () => {
    expect(lookupCountryDefault('HR')).toEqual({ region: 'Croatia', currency: 'EUR' });
    expect(lookupCountryDefault('hr')).toEqual({ region: 'Croatia', currency: 'EUR' });
  });
});

describe('Bulgaria', () => {
  it('does not offer the lev for a new project, the euro replaced it on 2026-01-01', () => {
    expect(CURRENCY_CODES.has('BGN')).toBe(false);
  });

  it('lists the euro as Bulgaria\'s currency', () => {
    expect(COUNTRIES.find((country) => country.code === 'BG')?.currency).toBe('EUR');
  });
});
