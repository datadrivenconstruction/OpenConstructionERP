// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The limitation arithmetic this feature does client-side.
 *
 * The form shows the date a regime produces before the save, so the period is
 * counted in two places: here, and in `add_months` in the backend module
 * `app/modules/defects_liability/limitation.py`. If the two ever disagree the
 * user picks a regime, watches a date appear, saves, and gets a different date
 * back. The cases below are the same cases the backend test asserts, so a drift
 * in either direction fails somewhere.
 */

import { describe, it, expect } from 'vitest';
import { LIMITATION_REGIMES, limitationEndDate, limitationRegime } from './api';

const ACCEPTANCE = '2026-03-01';

describe('limitationRegime', () => {
  it('ships the four-year and five-year regimes and nothing else', () => {
    expect(LIMITATION_REGIMES.map((r) => r.code)).toEqual([
      'de_vob_b',
      'de_bgb',
      'eg_civil_651',
      'fr_civil_1792_6',
      'fr_civil_1792_3',
      'fr_civil_1792',
      'sa_sbc_decennial',
    ]);
    expect(limitationRegime('de_vob_b')?.months).toBe(48);
    expect(limitationRegime('de_bgb')?.months).toBe(60);
    expect(limitationRegime('eg_civil_651')?.months).toBe(120);
    expect(limitationRegime('fr_civil_1792_6')?.months).toBe(12);
    expect(limitationRegime('fr_civil_1792_3')?.months).toBe(24);
    expect(limitationRegime('fr_civil_1792')?.months).toBe(120);
    expect(limitationRegime('sa_sbc_decennial')?.months).toBe(120);
  });

  it('treats no regime and an unknown regime alike, as no regime', () => {
    expect(limitationRegime(null)).toBeUndefined();
    expect(limitationRegime('')).toBeUndefined();
    expect(limitationRegime('de_wishful')).toBeUndefined();
  });
});

describe('limitationEndDate', () => {
  it('gives the VOB/B and BGB dates a year apart from the same acceptance', () => {
    expect(limitationEndDate(ACCEPTANCE, 48)).toBe('2030-03-01');
    expect(limitationEndDate(ACCEPTANCE, 60)).toBe('2031-03-01');
  });

  it.each([
    // § 188 Abs. 3 BGB: a final month with no matching day ends on its last day.
    ['2024-08-31', 6, '2025-02-28'],
    ['2023-08-31', 6, '2024-02-29'],
    ['2026-05-31', 48, '2030-05-31'],
    // An acceptance on a leap day: four years later the day exists, five not.
    ['2024-02-29', 48, '2028-02-29'],
    ['2024-02-29', 60, '2029-02-28'],
    // Year rollover, and the degenerate zero-month period.
    ['2026-12-31', 1, '2027-01-31'],
    ['2026-03-01', 0, '2026-03-01'],
  ])('counts %s + %i months to %s', (start, months, expected) => {
    expect(limitationEndDate(start as string, months as number)).toBe(expected);
  });

  it('returns nothing rather than inventing a date with no acceptance to count from', () => {
    expect(limitationEndDate('', 48)).toBe('');
    expect(limitationEndDate('not-a-date', 48)).toBe('');
  });
});
