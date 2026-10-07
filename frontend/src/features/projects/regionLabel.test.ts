// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { regionOptionLabel } from './regionLabel';
import { getCountry } from '@/shared/lib/countries';
import projectPageSource from './CreateProjectPage.tsx?raw';

// P-55: a Croatian estimator looked for "Hrvatska" in the region list and
// found only the English "Croatia".
describe('regionOptionLabel', () => {
  const croatia = { value: 'Croatia', label: 'Croatia', iso: 'HR' };

  it('names a single-country region in the reader language', () => {
    expect(regionOptionLabel(croatia, 'hr')).toBe('Hrvatska');
    expect(regionOptionLabel(croatia, 'de')).toBe('Kroatien');
    expect(regionOptionLabel(croatia, 'en')).toBe('Croatia');
  });

  it('keeps the label of a grouping that is not one country', () => {
    const dach = { value: 'DACH', label: 'DACH (Germany, Austria, Switzerland)' };
    expect(regionOptionLabel(dach, 'hr')).toBe('DACH (Germany, Austria, Switzerland)');
  });

  it('falls back to the label for an unknown language tag', () => {
    expect(regionOptionLabel(croatia, '')).toBe('Croatia');
  });
});

// JUR-03: both countries already exist in the shared registry but were absent
// from the creation/edit selector. Check the shipped options, not test fixtures.
describe('Hungarian and Ukrainian project regions', () => {
  it.each([
    ['HU', 'hu', 'Magyarország'],
    ['UA', 'uk', 'Україна'],
  ])('offers %s with its localized country name', (iso, lang, localized) => {
    const block = projectPageSource.split('const REGION_GROUPS')[1]?.split('\n];')[0] ?? '';
    const options = [...block.matchAll(/value: '([^']+)', label: '([^']+)', iso: '([^']+)'/g)]
      .map((match) => ({ value: match[1]!, label: match[2]!, iso: match[3]! }));
    const matches = options.filter((option) => option.iso === iso);
    expect(matches).toHaveLength(1);
    const option = matches[0];
    if (!option) throw new Error(`Missing region option ${iso}`);
    expect(option.value).toBe(iso);
    expect(option.label).toBe(getCountry(iso)?.name);
    expect(regionOptionLabel(option, lang)).toBe(localized);
  });
});
