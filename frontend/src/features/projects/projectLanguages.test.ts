// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A language a person can pick for the interface must also be one they can pick
// for a project. Ukrainian was the case that was reported: offered in the
// header, missing from the project form, so the project went out as "other".

import { readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { PROJECT_LANGUAGES } from './projectLanguages';

const BACKEND_LOCALES = join(dirname(fileURLToPath(import.meta.url)), '../../../../backend/locales');

describe('project languages', () => {
  it('offers Ukrainian under its own code', () => {
    const uk = PROJECT_LANGUAGES.find((l) => l.value === 'uk');
    expect(uk?.label).toBe('Українська');
  });

  it('offers every base language of the interface picker', () => {
    const base = SUPPORTED_LANGUAGES.map((l) => l.code).filter((c) => !c.includes('-'));
    expect(PROJECT_LANGUAGES.map((l) => l.value)).toEqual(base);
  });

  it('leaves the regional variants out', () => {
    expect(PROJECT_LANGUAGES.some((l) => l.value.includes('-'))).toBe(false);
  });

  it('offers only languages the backend has a locale file for', () => {
    const files = new Set(readdirSync(BACKEND_LOCALES).map((f) => f.replace(/\.json$/, '')));
    const missing = PROJECT_LANGUAGES.map((l) => l.value).filter((c) => !files.has(c));
    expect(missing).toEqual([]);
  });

  it('keeps the languages the form offered before', () => {
    const before = ['en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'cs', 'hr', 'hu', 'ru', 'tr', 'ar', 'zh', 'ja',
      'ko', 'hi', 'th', 'vi', 'id', 'sv', 'no', 'da', 'fi'];
    const offered = new Set(PROJECT_LANGUAGES.map((l) => l.value));
    expect(before.filter((c) => !offered.has(c))).toEqual([]);
  });
});
