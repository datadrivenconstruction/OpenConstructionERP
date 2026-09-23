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
  groupProfilePresets,
} from '../profileGroups';

const HERE = dirname(fileURLToPath(import.meta.url));
const PRESETS_PY = resolve(HERE, '../../../../../backend/app/core/onboarding_presets.py');

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
