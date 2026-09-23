// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The profile step files each backend preset as a business, a job, or the
// catch-all. The filing is a list of keys in the frontend and the presets live
// in Python, so the two can drift apart without either side noticing: a new
// preset would fall into the business group by default, and a renamed one
// would leave a dead key here. Both are caught against the source file itself.

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  COMPANY_PROFILE_ORDER,
  EVERYTHING_PROFILE_KEY,
  ROLE_PROFILE_KEYS,
  activeModuleCount,
  companyTypeToSave,
  groupProfilePresets,
} from '../profileGroups';
import { ALL_MODULES, CORE_MODULE_KEYS } from '../modules';

const HERE = dirname(fileURLToPath(import.meta.url));
const PRESETS_PY = resolve(HERE, '../../../../../backend/app/core/onboarding_presets.py');
const EN_LOCALE = resolve(HERE, '../../../app/locales/en.ts');

/** COMPANY_PRESETS keys, read from the backend source. The size presets are
 *  declared after them in the same file and are cut off here. */
function backendPresetKeys(): string[] {
  const text = readFileSync(PRESETS_PY, 'utf-8');
  const start = text.indexOf('COMPANY_PRESETS: dict');
  const end = text.indexOf('SIZE_PRESETS: dict');
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(start);
  const keys = [...text.slice(start, end).matchAll(/key="([a-z0-9_]+)"/g)].map((m) => m[1]!);
  expect(keys.length).toBeGreaterThanOrEqual(9);
  return keys;
}

describe('profile groups against the backend catalogue', () => {
  const keys = backendPresetKeys();

  it('files every backend preset in exactly one place', () => {
    const unfiled = keys.filter(
      (k) => !COMPANY_PROFILE_ORDER.includes(k) && !ROLE_PROFILE_KEYS.has(k) && k !== EVERYTHING_PROFILE_KEY,
    );
    expect(unfiled, 'add the new preset to COMPANY_PROFILE_ORDER or ROLE_PROFILE_KEYS').toEqual([]);

    const twice = COMPANY_PROFILE_ORDER.filter((k) => ROLE_PROFILE_KEYS.has(k));
    expect(twice).toEqual([]);
    expect(new Set(COMPANY_PROFILE_ORDER).size).toBe(COMPANY_PROFILE_ORDER.length);
  });

  it('names no preset the backend does not serve', () => {
    const served = new Set(keys);
    const filed = [...COMPANY_PROFILE_ORDER, ...ROLE_PROFILE_KEYS, EVERYTHING_PROFILE_KEY];
    expect(filed.filter((k) => !served.has(k))).toEqual([]);
  });

  it('names every profile in words the reader has, not in the backend English', () => {
    // A card takes its name and one-line description from
    // `onboarding.company_<key>` and `_desc`, and falls back to the English the
    // endpoint serves. A key with no locale entry would read in English in
    // every language, and no orphan-key gate can see a computed key.
    const en = readFileSync(EN_LOCALE, 'utf-8');
    const unnamed = keys.filter(
      (k) => !en.includes(`"onboarding.company_${k}":`) || !en.includes(`"onboarding.company_${k}_desc":`),
    );
    expect(unnamed).toEqual([]);
  });

  it('leads with businesses and keeps the size tiers out entirely', () => {
    const groups = groupProfilePresets(keys.map((key) => ({ key })));
    expect(groups.companies.map((p) => p.key)).toEqual([...COMPANY_PROFILE_ORDER]);
    expect(groups.everything?.key).toBe(EVERYTHING_PROFILE_KEY);
    expect(groups.roles.map((p) => p.key).sort()).toEqual([...ROLE_PROFILE_KEYS].sort());
    const all = [...groups.companies, ...groups.roles, groups.everything].map((p) => p?.key ?? '');
    expect(all.some((k) => k.startsWith('size_'))).toBe(false);
  });
});

describe('groupProfilePresets', () => {
  it('puts a key filed nowhere among the businesses, after the ordered ones', () => {
    const groups = groupProfilePresets([
      { key: 'demolition_contractor' },
      { key: 'subcontractor' },
      { key: 'hse_manager' },
      { key: 'general_contractor' },
    ]);
    expect(groups.companies.map((p) => p.key)).toEqual([
      'general_contractor',
      'subcontractor',
      'demolition_contractor',
    ]);
    expect(groups.roles.map((p) => p.key)).toEqual(['hse_manager']);
    expect(groups.everything).toBeNull();
  });
});

describe('companyTypeToSave', () => {
  const everything = new Set(ALL_MODULES.filter((m) => !m.core).map((m) => m.key));
  const without = (key: string) => new Set([...everything].filter((k) => k !== key));

  it('saves a picked profile as picked, whatever was switched after it', () => {
    expect(companyTypeToSave('general_contractor', new Set(['boq']))).toBe('general_contractor');
    expect(companyTypeToSave('general_contractor', everything)).toBe('general_contractor');
  });

  it('saves the catch-all, or no pick at all, as the catch-all while every module is on', () => {
    expect(companyTypeToSave(EVERYTHING_PROFILE_KEY, everything)).toBe(EVERYTHING_PROFILE_KEY);
    expect(companyTypeToSave(null, everything)).toBe(EVERYTHING_PROFILE_KEY);
  });

  it('saves no profile once a module is switched off, so the server keeps the choice', () => {
    expect(companyTypeToSave(EVERYTHING_PROFILE_KEY, without('finance'))).toBeNull();
    expect(companyTypeToSave(null, without('crm'))).toBeNull();
  });

  it('ignores the regional packs, which no profile governs', () => {
    const pack = ALL_MODULES.find((m) => m.group === 'regional')!.key;
    expect(companyTypeToSave(null, without(pack))).toBe(EVERYTHING_PROFILE_KEY);
  });
});

describe('activeModuleCount', () => {
  it('counts a core module a preset re-lists once', () => {
    const core = [...CORE_MODULE_KEYS][0]!;
    expect(activeModuleCount(['boq', core])).toBe(CORE_MODULE_KEYS.size + 1);
    expect(activeModuleCount([])).toBe(CORE_MODULE_KEYS.size);
  });
});
