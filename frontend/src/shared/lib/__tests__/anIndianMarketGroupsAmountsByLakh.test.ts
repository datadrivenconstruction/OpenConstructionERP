// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// An Indian bill of quantities printed `476,579,722.78`. The number is right
// and the way it is written is not: India groups the last three digits and
// then twos, so every estimator, contractor and auditor in that market reads
// that figure as `47,65,79,722.78`. A bill grouped the Western way reads as
// somebody else's document.
//
// `Intl` already knows this - `en-IN` produces the lakh grouping with no
// custom code - so the defect was never the arithmetic, it was which tag
// reached the formatter. `resolveNumberLocale` answered `'auto'` with the UI
// LANGUAGE, and the UI language of an Indian workspace is usually English,
// which resolves to `en-US`. Nothing in the chain ever asked which market the
// workspace serves.
//
// The half of this that a happy-path test cannot see is the mechanism. Two
// assertions below pin it, and both fail against any fix that merely re-tags
// the reader's own language with an Indian region:
//
//   - A GERMAN reader still gets lakh grouping, because the grouping belongs
//     to the document's market and not to whoever opened it. Measured,
//     `de-IN` resolves to plain `de` and prints `476.579.722,78`, so this
//     assertion is only satisfiable by carrying a tag CLDR has Indian number
//     data for.
//   - A reader who explicitly picked `de-DE` keeps it. The market is a
//     fallback for `'auto'`, never an override, which is what keeps this from
//     becoming a second answer to "which locale does the reader read numbers
//     in".
import i18next from 'i18next';
import { afterAll, beforeEach, describe, expect, it } from 'vitest';

import { formatCurrency } from '../money';
import { getMarketNumberLocale, setMarketNumberLocale } from '../marketNumberLocale';
import { numberLocaleForCountry, usePreferencesStore } from '@/stores/usePreferencesStore';

void i18next.init({ lng: 'en', resources: {}, initImmediate: false });
const originalLanguage = i18next.language;
afterAll(() => {
  setMarketNumberLocale(null);
  void i18next.changeLanguage(originalLanguage);
});

// The amount from the report, and the two ways it can be written.
const AMOUNT = 476_579_722.78;
const LAKH = '47,65,79,722.78';
const WESTERN = '476,579,722.78';
const GERMAN = '476.579.722,78';

describe('an Indian market groups amounts by lakh', () => {
  beforeEach(async () => {
    localStorage.clear();
    usePreferencesStore.getState().resetPreferences();
    setMarketNumberLocale(null);
    await i18next.changeLanguage('en');
  });

  it('writes an Indian amount the way India writes it', () => {
    setMarketNumberLocale('en-IN');
    expect(formatCurrency(AMOUNT, 'INR')).toContain(LAKH);
  });

  it('keeps the lakh grouping for a German reader, because it belongs to the document', async () => {
    // The discriminator. `de-IN` is not a locale CLDR carries number data for
    // - it falls back to `de` and groups by threes - so a fix that re-regions
    // the reader's language fails here while passing the English case above.
    setMarketNumberLocale('en-IN');
    await i18next.changeLanguage('de');
    const text = formatCurrency(AMOUNT, 'INR');
    expect(text).toContain(LAKH);
    expect(text).not.toContain(GERMAN);
  });

  it('lets a reader who chose a format keep it', () => {
    // The market answers `'auto'` only. A reader who went to regional settings
    // and picked German separators asked for them on every document.
    setMarketNumberLocale('en-IN');
    usePreferencesStore.getState().setPreference('numberLocale', 'de-DE');
    const text = formatCurrency(AMOUNT, 'INR');
    expect(text).toContain(GERMAN);
    expect(text).not.toContain(LAKH);
  });

  it('leaves a workspace with no market exactly where it was', () => {
    // No pack applied is the state most installs are in, and this is the
    // behaviour they have today: `'auto'` follows the UI language.
    expect(getMarketNumberLocale()).toBeNull();
    expect(formatCurrency(AMOUNT, 'INR')).toContain(WESTERN);
  });

  it('gives the grouping back when the pack is un-applied', () => {
    // `resetPackLocale` puts the UI language back on deactivate; the market
    // tag has to go with it, or an un-applied India pack leaves lakh grouping
    // behind with nothing in the UI able to reach it.
    setMarketNumberLocale('en-IN');
    expect(formatCurrency(AMOUNT, 'INR')).toContain(LAKH);
    setMarketNumberLocale(null);
    expect(formatCurrency(AMOUNT, 'INR')).toContain(WESTERN);
  });
});

describe('numberLocaleForCountry', () => {
  it('answers India with the tag Intl has Indian number data for', () => {
    expect(numberLocaleForCountry('in')).toBe('en-IN');
    expect(numberLocaleForCountry('IN')).toBe('en-IN');
  });

  it('says nothing for a country whose grouping the reader already gets', () => {
    // A country only earns an entry when its tag changes the grouping. `de`
    // and `us` are already what the UI language resolves to, and answering
    // them here would override a German reader's own separators with a second
    // opinion that agrees with nobody.
    expect(numberLocaleForCountry('de')).toBeNull();
    expect(numberLocaleForCountry('us')).toBeNull();
    expect(numberLocaleForCountry('xx')).toBeNull();
    expect(numberLocaleForCountry(null)).toBeNull();
  });

  it('does not claim the South Asian neighbours', () => {
    // Measured, not assumed: `en-PK`, `en-BD`, `en-LK` and `en-NP` all resolve
    // to plain `en` and group by threes, so there is no tag to map them onto
    // and an entry here would be a promise the engine cannot keep. Pakistan,
    // Bangladesh, Sri Lanka and Nepal use the same lakh/crore system in life
    // and need their own answer, not this one.
    for (const cc of ['pk', 'bd', 'lk', 'np']) {
      expect(numberLocaleForCountry(cc)).toBeNull();
    }
  });
});
