// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// A Swiss bill is written 1'234'567.89. A German-speaking Swiss reader runs the
// German UI, which resolves to `de` and writes 1.234.567,89, so without a
// country answer every Swiss amount on screen used German separators and a
// decimal comma. These tests measure what Intl actually prints rather than
// what someone remembers it prints: on ICU 78.3 (CLDR 48) the Swiss group
// separator is the ASCII apostrophe, not the typographic U+2019 older CLDR
// releases used.
//
// The same file holds the Irish and Ukrainian picker entries, because they are
// the other half of the same wave: Ireland had a country default on the server
// and no way to be chosen here, and the hryvnia could not be picked at all.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  NUMBER_LOCALES,
  adoptServerNumberFormat,
  numberLocaleForCountry,
} from '@/stores/usePreferencesStore';
import {
  COUNTRY_DEFAULTS,
  CURRENCY_GROUPS,
  lookupCountryDefault,
} from '@/features/projects/currencyGroups';

const SAMPLE = 1234567.89;

function createProjectSource(): string {
  return readFileSync(resolve(__dirname, '../../../features/projects/CreateProjectPage.tsx'), 'utf-8');
}

describe('Swiss number grouping', () => {
  it('is what Intl prints for de-CH, and is not the German answer', () => {
    const swiss = new Intl.NumberFormat('de-CH', { minimumFractionDigits: 2 }).format(SAMPLE);
    const german = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2 }).format(SAMPLE);
    expect(swiss).toBe("1'234'567.89");
    expect(german).toBe('1.234.567,89');
    expect(swiss).not.toBe(german);
  });

  it('is the same grouping in the French and Italian Swiss locales', () => {
    // Why mapping the whole country to `de-CH` is right for a Geneva or Lugano
    // workspace too: the apostrophe grouping is shared. The decimal mark in
    // `fr-CH` is a comma, which a Swiss bill does not use for francs.
    expect(new Intl.NumberFormat('it-CH', { minimumFractionDigits: 2 }).format(SAMPLE)).toBe("1'234'567.89");
    expect(new Intl.NumberFormat('fr-CH', { minimumFractionDigits: 2 }).format(SAMPLE)).toContain("1'234'567");
  });

  it('answers Switzerland with de-CH, in any case', () => {
    expect(numberLocaleForCountry('ch')).toBe('de-CH');
    expect(numberLocaleForCountry(' CH ')).toBe('de-CH');
  });

  it('keeps India and still says nothing for Germany or an unknown code', () => {
    expect(numberLocaleForCountry('in')).toBe('en-IN');
    expect(numberLocaleForCountry('de')).toBeNull();
    expect(numberLocaleForCountry('xx')).toBeNull();
  });

  it('does not answer a property name inherited from Object', () => {
    // A plain object table would hand back a function for these.
    expect(numberLocaleForCountry('constructor')).toBeNull();
    expect(numberLocaleForCountry('__proto__')).toBeNull();
  });

  it('is a choice the regional settings picker offers', () => {
    expect(NUMBER_LOCALES).toContain('de-CH');
  });

  it('reads both spellings of the Swiss account pattern', () => {
    expect(adoptServerNumberFormat("1'234.56", 'auto')).toBe('de-CH');
    expect(adoptServerNumberFormat('1’234.56', 'auto')).toBe('de-CH');
    expect(adoptServerNumberFormat('de-CH', 'auto')).toBe('de-CH');
  });

  it('reads the lakh pattern the server files India under', () => {
    expect(adoptServerNumberFormat('12,34,567.89', 'auto')).toBe('en-IN');
  });
});

describe('the project pickers', () => {
  it('fill an Irish address with the Irish region and the euro', () => {
    expect(lookupCountryDefault('IE')).toEqual({ region: 'Ireland', currency: 'EUR' });
  });

  it('offer every region and currency the country defaults name', () => {
    // The auto-fill silently does nothing for a value no option carries, so
    // a default pointing at a missing option looks fine and fills nothing.
    const regionBlock = createProjectSource().split('const REGION_GROUPS')[1]?.split('\n];')[0] ?? '';
    const regions = new Set([...regionBlock.matchAll(/value:\s*'([^']+)'/g)].map((m) => m[1]));
    const currencies = new Set(CURRENCY_GROUPS.flatMap((g) => g.options.map((o) => o.value)));
    expect(regions.size).toBeGreaterThan(20);
    for (const [cc, entry] of Object.entries(COUNTRY_DEFAULTS)) {
      expect(regions.has(entry.region), `${cc} -> region ${entry.region}`).toBe(true);
      expect(currencies.has(entry.currency), `${cc} -> currency ${entry.currency}`).toBe(true);
    }
  });

  it('offer the hryvnia in both currency lists', () => {
    expect(CURRENCY_GROUPS.flatMap((g) => g.options.map((o) => o.value))).toContain('UAH');
    expect(createProjectSource()).toContain("{ value: 'UAH', label: 'UAH (₴) - Ukrainian Hryvnia' }");
  });

  it('write a hryvnia amount spaced, the Ukrainian way', () => {
    const text = new Intl.NumberFormat('uk-UA', { style: 'currency', currency: 'UAH' }).format(SAMPLE);
    expect(text.replace(/\s/g, ' ')).toContain('1 234 567,89');
  });
});
