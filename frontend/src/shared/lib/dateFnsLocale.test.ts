// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Guards the map that keeps relative timestamps out of English.
 *
 * The defect this replaces was invisible to every gate we own, because
 * `formatDistanceToNow(d, { addSuffix: true })` is valid code that returns a
 * valid string. It just returns an English one, forever, in all forty-two
 * languages. Nothing throws and nothing renders a raw key, so the only
 * instrument that catches it is one that names the language it expects.
 *
 * The table below is written out rather than derived, because a derived
 * expectation would reproduce whatever the map says and agree with itself.
 */
import { describe, it, expect } from 'vitest';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { dateFnsLocaleFor, LANGUAGES_WITHOUT_DATE_FNS_LOCALE } from './dateFnsLocale';

/** i18next code → the `code` field of the date-fns locale it must resolve to. */
const EXPECTED: Record<string, string> = {
  en: 'en-US',
  'en-US': 'en-US',
  de: 'de',
  fr: 'fr',
  es: 'es',
  'es-MX': 'es',
  'es-CL': 'es',
  'es-CO': 'es',
  pt: 'pt',
  'pt-BR': 'pt-BR',
  ru: 'ru',
  zh: 'zh-CN',
  ar: 'ar',
  hi: 'hi',
  tr: 'tr',
  it: 'it',
  nl: 'nl',
  pl: 'pl',
  cs: 'cs',
  ja: 'ja',
  ko: 'ko',
  sv: 'sv',
  no: 'nb',
  da: 'da',
  fi: 'fi',
  bg: 'bg',
  hr: 'hr',
  id: 'id',
  ro: 'ro',
  th: 'th',
  vi: 'vi',
  ky: 'en-US',
  et: 'et',
  bn: 'bn',
  kk: 'kk',
  fil: 'en-US',
  ur: 'en-US',
  fa: 'fa-IR',
  he: 'he',
  el: 'el',
  uk: 'uk',
  uz: 'uz',
};

describe('date-fns locale resolution', () => {
  it('resolves every supported language to the locale named for it', () => {
    for (const { code } of SUPPORTED_LANGUAGES) {
      const expected = EXPECTED[code];
      expect(expected, `no expectation recorded for language "${code}"`).toBeDefined();
      expect(dateFnsLocaleFor(code).code, `language "${code}"`).toBe(expected);
    }
  });

  it('covers every supported language and nothing that is not one', () => {
    // A language added to the picker with no entry here would otherwise fall
    // through to English and ship looking finished.
    const supported = SUPPORTED_LANGUAGES.map((l) => l.code).sort();
    expect(Object.keys(EXPECTED).sort()).toEqual(supported);
  });

  it('falls back to English only for the three languages date-fns has no locale for', () => {
    // Asserted in both directions on purpose. The first half says the gap is
    // where we think it is; the second says nothing else quietly joined it,
    // which is the failure mode that put this defect in front of readers.
    const gaps = [...LANGUAGES_WITHOUT_DATE_FNS_LOCALE];
    for (const code of gaps) {
      expect(dateFnsLocaleFor(code).code, `known gap "${code}"`).toBe('en-US');
    }
    const fallingBack = SUPPORTED_LANGUAGES.map((l) => l.code)
      .filter((c) => !c.startsWith('en'))
      .filter((c) => dateFnsLocaleFor(c).code === 'en-US')
      .sort();
    expect(fallingBack).toEqual([...gaps].sort());
  });

  it('resolves a regional code through its base language', () => {
    // Regional Spanish is not in the map by name; it must not land on English.
    expect(dateFnsLocaleFor('es-419').code).toBe('es');
    expect(dateFnsLocaleFor('de-AT').code).toBe('de');
  });

  it('answers English for an empty or unknown language rather than throwing', () => {
    expect(dateFnsLocaleFor(undefined).code).toBe('en-US');
    expect(dateFnsLocaleFor('').code).toBe('en-US');
    expect(dateFnsLocaleFor('qqq').code).toBe('en-US');
  });
});
