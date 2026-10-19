// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Which digits a number prints in is its own preference. Arabic prints
// Arabic-Indic digits by default, while Egyptian business documents commonly
// use Western ones, and an English reader may want the opposite. The choice
// is applied where the product already answers "which locale": in
// `getIntlLocale` (dates, lists) and in `resolveNumberLocale` (numbers,
// money), so no formatter needs to know it exists. These tests watch it arrive
// at the formatters rather than at the resolver, because a resolver that is
// right and a formatter that bypasses it is the defect worth catching.
import { describe, it, expect, afterEach, beforeEach } from 'vitest';
import i18next from 'i18next';
import { fmtCurrency, fmtDate, fmtNumber, getIntlLocale } from '../formatters';
import { withDigitSystem, getDigitSystem } from '../intlLocale';
import { digitSystemHeader } from '../api';
import { NUMBER_LOCALES, usePreferencesStore } from '@/stores/usePreferencesStore';
import { getCurrencySymbol } from '@/features/boq/boqHelpers';

const ARABIC_INDIC = /[٠-٩]/;
const WESTERN = /[0-9]/;

// The suite needs a language switch and nothing to translate, the way the
// Indian and list-joining suites beside it set i18next up.
void i18next.init({ lng: 'en', resources: {}, initAsync: false });

let language: string;

beforeEach(() => {
  language = i18next.language;
});

afterEach(async () => {
  usePreferencesStore.getState().resetPreferences();
  await i18next.changeLanguage(language);
});

describe('digit system', () => {
  it('leaves every tag alone on automatic', async () => {
    await i18next.changeLanguage('en');
    expect(getDigitSystem()).toBe('auto');
    expect(getIntlLocale()).toBe('en');
    expect(digitSystemHeader()).toBeNull();
  });

  it('gives an Arabic reader Western digits in money and dates', async () => {
    await i18next.changeLanguage('ar');
    expect(fmtNumber(1234.5)).toMatch(ARABIC_INDIC);

    usePreferencesStore.getState().setPreference('digitSystem', 'latn');
    expect(getDigitSystem()).toBe('latn');
    const money = fmtCurrency(1234.5, 'EGP');
    expect(money).toMatch(WESTERN);
    expect(money).not.toMatch(ARABIC_INDIC);
    expect(money).toContain('ج.م');
    expect(fmtDate('2026-10-19')).not.toMatch(ARABIC_INDIC);
    expect(digitSystemHeader()).toBe('latn');
  });

  it('gives an English reader Arabic-Indic digits when asked', async () => {
    await i18next.changeLanguage('en');
    usePreferencesStore.getState().setPreference('digitSystem', 'arab');
    expect(fmtNumber(1234.5)).toMatch(ARABIC_INDIC);
    expect(fmtDate('2026-10-19')).toMatch(ARABIC_INDIC);
  });

  it('applies on top of an explicit number format too', async () => {
    await i18next.changeLanguage('en');
    usePreferencesStore.getState().setPreferences({ numberLocale: 'ar-EG', digitSystem: 'latn' });
    const text = fmtNumber(1234567.5);
    expect(text).not.toMatch(ARABIC_INDIC);
    expect(text).toContain('1,234,567.5');
  });

  it('is idempotent and keeps a tag that already writes those digits', () => {
    expect(withDigitSystem('en', 'latn')).toBe('en');
    expect(withDigitSystem('ar-EG', 'latn')).toBe('ar-EG-u-nu-latn');
    expect(withDigitSystem('ar-EG-u-nu-latn', 'latn')).toBe('ar-EG-u-nu-latn');
    expect(withDigitSystem('ar-EG-u-nu-latn', 'arab')).toBe('ar-EG-u-nu-arab');
    expect(withDigitSystem('fa', 'arabext')).toBe('fa');
  });

  it('offers Egyptian conventions as a number format', () => {
    expect(NUMBER_LOCALES).toContain('ar-EG');
  });

  it('adopts a server choice only when it is a real one', async () => {
    const store = usePreferencesStore.getState();
    store.setPreference('digitSystem', 'arab');
    const original = globalThis.fetch;
    const respond = (digit_system: string) =>
      (globalThis.fetch = (async () =>
        new Response(JSON.stringify({ digit_system }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })) as typeof fetch);
    try {
      respond('auto');
      await usePreferencesStore.getState().hydrateFromServer();
      expect(usePreferencesStore.getState().digitSystem).toBe('arab');
      respond('roman');
      await usePreferencesStore.getState().hydrateFromServer();
      expect(usePreferencesStore.getState().digitSystem).toBe('arab');
      respond('latn');
      await usePreferencesStore.getState().hydrateFromServer();
      expect(usePreferencesStore.getState().digitSystem).toBe('latn');
    } finally {
      globalThis.fetch = original;
    }
  });
});

describe('currency symbol in a header', () => {
  it('follows the Arabic reader for the Egyptian pound and stays Latin for others', async () => {
    await i18next.changeLanguage('en');
    expect(getCurrencySymbol('EGP')).toBe('E£');
    await i18next.changeLanguage('ar');
    expect(getCurrencySymbol('EGP')).toMatch(/^ج\.م/);
    expect(getCurrencySymbol('EUR')).toBe('€');
  });
});
