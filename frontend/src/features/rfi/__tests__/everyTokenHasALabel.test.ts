// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The RFI screen builds its priority, discipline and status labels from the
// stored token (`rfi.priority_${p}`). The priority and discipline keys did not
// exist in any locale, so the screen fell back to the token with a capital
// letter: an English word on a Turkish screen, and "Mep" for MEP. This holds
// the two locales the Turkish pilot reads to the full set of tokens: the
// priorities the backend accepts (the pattern in
// backend/app/modules/rfi/schemas.py), the disciplines the picker offers and
// the five statuses.

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { RFI_DISCIPLINES } from '../api';

const PRIORITIES = ['low', 'normal', 'high', 'critical'];
const STATUSES = ['draft', 'open', 'answered', 'closed', 'void'];

const KEYS = [
  ...PRIORITIES.map((p) => `rfi.priority_${p}`),
  ...RFI_DISCIPLINES.map((d) => `rfi.discipline_${d}`),
  ...STATUSES.map((s) => `rfi.status_${s}`),
];

function valueOf(locale: string, key: string): string | null {
  const source = readFileSync(resolve(__dirname, `../../../app/locales/${locale}.ts`), 'utf8');
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(`^\\s*"${escaped}":\\s*"((?:[^"\\\\]|\\\\.)*)"`, 'm').exec(source);
  return match?.[1] ?? null;
}

describe('every RFI token the screen can show has a label', () => {
  it.each(KEYS)('%s is in English and in Turkish', (key) => {
    expect(valueOf('en', key), `${key} in en`).toBeTruthy();
    expect(valueOf('tr', key), `${key} in tr`).toBeTruthy();
  });

  it('writes MEP as an abbreviation in English, not as a capitalised word', () => {
    expect(valueOf('en', 'rfi.discipline_mep')).toBe('MEP');
  });

  it('gives Turkish its own words for the words that differ from English', () => {
    for (const key of ['rfi.priority_low', 'rfi.priority_high', 'rfi.discipline_structural']) {
      expect(valueOf('tr', key), key).not.toBe(valueOf('en', key));
    }
  });
});
