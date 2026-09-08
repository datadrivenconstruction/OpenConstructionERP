// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Writing direction has to follow the active language, and it has to do it at
// three separate moments that fail independently: on <html> at all, from the
// language the reader actually picked, and again when they pick another one at
// runtime. Four of the languages we offer are written right to left, and for
// them a page left in `dir="ltr"` puts the sidebar on the wrong edge and every
// label against the wrong margin while the strings themselves are perfectly
// translated - so the product reads as broken rather than as untranslated, and
// nothing in the string-level i18n gates can see it.
//
// The population is derived from `SUPPORTED_LANGUAGES` rather than written out
// as ['ar','fa','he','ur']. A hardcoded list would keep passing on the day a
// fifth right-to-left language is added without direction support, which is the
// exact regression this file exists to catch; deriving it means the new entry
// joins the assertion by existing.
//
// Run:  npx vitest run src/app/__tests__/documentDirectionFollowsTheLanguage.test.ts

import { describe, expect, it, afterAll } from 'vitest';

import i18n, {
  SUPPORTED_LANGUAGES,
  applyDocumentDirection,
  resolveDirection,
} from '../i18n';

/** Languages we offer that declare right-to-left, read off the shipped list. */
const RTL = SUPPORTED_LANGUAGES.filter((l) => 'dir' in l && l.dir === 'rtl').map((l) => l.code);
const LTR = SUPPORTED_LANGUAGES.filter((l) => !('dir' in l && l.dir === 'rtl')).map((l) => l.code);

describe('document direction follows the active language', () => {
  afterAll(async () => {
    // Leave the shared jsdom document and the shared i18next instance the way
    // this file found them, so a test that runs after this one in the same
    // worker does not inherit an Arabic document.
    await i18n.changeLanguage('en');
  });

  it('offers exactly four right-to-left languages, and names them', () => {
    // The population, printed beside the verdict: 43 languages offered, of
    // which 4 are RTL. A suite that asserted only the four would not notice
    // the denominator moving underneath it. The denominator moved here when
    // English (UK) joined the picker, and this is the assertion that said so -
    // which is the whole point of writing it as one string rather than as two
    // independent expectations.
    expect(
      `${RTL.length} of ${SUPPORTED_LANGUAGES.length} offered languages are RTL: ${RTL.join(', ')}`,
    ).toBe('4 of 43 offered languages are RTL: ar, ur, fa, he');
  });

  it('resolves rtl for every right-to-left language', () => {
    expect(RTL.map(resolveDirection)).toEqual(RTL.map(() => 'rtl'));
  });

  it('resolves ltr for every other language, so the flip is not indiscriminate', () => {
    // The other half of the both-directions requirement. Were `resolveDirection`
    // to answer 'rtl' for everything - or for one language by accident - the
    // assertion above would still pass and this one would fail.
    const wrong = LTR.filter((code) => resolveDirection(code) !== 'ltr');
    expect({ checked: LTR.length, wrong }).toEqual({ checked: 38, wrong: [] });
  });

  it('writes dir and lang onto <html> for each right-to-left language', () => {
    for (const code of RTL) {
      applyDocumentDirection(code);
      expect(document.documentElement.dir).toBe('rtl');
      expect(document.documentElement.lang).toBe(code);
    }
  });

  it('returns the document to ltr for a control language', () => {
    applyDocumentDirection('ar');
    expect(document.documentElement.dir).toBe('rtl');
    applyDocumentDirection('de');
    expect(document.documentElement.dir).toBe('ltr');
    expect(document.documentElement.lang).toBe('de');
  });

  it('updates the document when the language changes at runtime', async () => {
    // The moment usually missed. This drives the real i18next instance so the
    // production `languageChanged` handler in i18n.ts is what does the work; a
    // test that called `applyDocumentDirection` itself would pass even if
    // nothing were subscribed to the event.
    await i18n.changeLanguage('en');
    expect(document.documentElement.dir).toBe('ltr');

    for (const code of RTL) {
      await i18n.changeLanguage(code);
      expect(document.documentElement.dir).toBe('rtl');
      expect(document.documentElement.lang).toBe(code);

      // ...and back, so a handler that only ever sets 'rtl' fails here.
      await i18n.changeLanguage('en');
      expect(document.documentElement.dir).toBe('ltr');
      expect(document.documentElement.lang).toBe('en');
    }
  });
});
