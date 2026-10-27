// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The languages the export menu offers are the ones the server can render, each
// under its own name, and the menu starts on the reader's own language.

import { describe, it, expect } from 'vitest';

import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import {
  DIARY_DOCUMENT_LOCALES,
  PURCHASING_DOCUMENT_LOCALES,
  REGISTER_DOCUMENT_LOCALES,
  defaultDocumentLocale,
  documentLocaleEnglishName,
  documentLocaleName,
} from './documentExport';

// Bengali is a backend language no bundled PDF face can draw, so the server answers it
// in English and the menu does not offer it. Urdu is set in runs of faces and is offered.
const NOT_RENDERABLE = new Set(['bn']);

// The interface also ships regional variants of a language (en-GB, pt-BR ...);
// a document language is the base language.
const BASE_INTERFACE_LANGUAGES = SUPPORTED_LANGUAGES.map((l) => l.code).filter((c) => !c.includes('-'));

describe('document languages', () => {
  it('offers every interface language the server renders, once each, and nothing else', () => {
    const expected = BASE_INTERFACE_LANGUAGES.filter((c) => !NOT_RENDERABLE.has(c));
    expect([...REGISTER_DOCUMENT_LOCALES].sort()).toEqual([...expected].sort());
    expect(new Set(REGISTER_DOCUMENT_LOCALES).size).toBe(REGISTER_DOCUMENT_LOCALES.length);
    expect(REGISTER_DOCUMENT_LOCALES[0]).toBe('en');
  });

  it('prints the diary in the same languages as the registers', () => {
    expect(DIARY_DOCUMENT_LOCALES).toEqual(REGISTER_DOCUMENT_LOCALES);
  });

  it('keeps the purchasing forms to the languages their catalogues hold', () => {
    expect([...PURCHASING_DOCUMENT_LOCALES].sort()).toEqual([...REGISTER_DOCUMENT_LOCALES].sort());
    expect(PURCHASING_DOCUMENT_LOCALES).not.toContain('bn');
  });

  it('names every language under its own name, never by its code', () => {
    for (const code of REGISTER_DOCUMENT_LOCALES) {
      const name = documentLocaleName(code);
      expect(name.length, code).toBeGreaterThan(1);
      expect(name, code).not.toBe(code.toUpperCase());
    }
    expect(documentLocaleName('en')).toBe('English');
    expect(documentLocaleName('de')).toBe('Deutsch');
    expect(documentLocaleName('tr')).toBe('Türkçe');
    expect(documentLocaleName('zh')).toBe('简体中文');
    expect(documentLocaleName('he')).toBe('עברית');
  });

  it('falls back to the runtime language names, then to the code', () => {
    expect(documentLocaleName('sw').toLowerCase()).toContain('swahili');
    expect(documentLocaleName('zz-not-a-language-tag-at-all')).toBe('ZZ-NOT-A-LANGUAGE-TAG-AT-ALL');
    // The hakedis certificate's combined choice keeps the spelling it always had.
    expect(documentLocaleName('tr-en')).toBe('TR-EN');
  });

  it('also names a language in English so a reader can search for it', () => {
    expect(documentLocaleEnglishName('de')).toBe('German');
    expect(documentLocaleEnglishName('en')).toBe('English');
    expect(documentLocaleEnglishName('fil')).toBe('Filipino');
  });

  it('starts on the interface language when the document exists in it, else English', () => {
    expect(defaultDocumentLocale(REGISTER_DOCUMENT_LOCALES, 'de-AT')).toBe('de');
    expect(defaultDocumentLocale(REGISTER_DOCUMENT_LOCALES, 'TR')).toBe('tr');
    expect(defaultDocumentLocale(REGISTER_DOCUMENT_LOCALES, 'bn')).toBe('en');
    expect(defaultDocumentLocale(REGISTER_DOCUMENT_LOCALES, 'sw')).toBe('en');
    expect(defaultDocumentLocale(REGISTER_DOCUMENT_LOCALES, null)).toBe('en');
    expect(defaultDocumentLocale(PURCHASING_DOCUMENT_LOCALES, 'ja')).toBe('ja');
    expect(defaultDocumentLocale(PURCHASING_DOCUMENT_LOCALES, 'bn')).toBe('en');
    expect(defaultDocumentLocale(PURCHASING_DOCUMENT_LOCALES, 'ar-EG')).toBe('ar');
  });
});
