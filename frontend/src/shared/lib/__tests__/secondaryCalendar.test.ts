// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { formatSecondaryDate, secondaryCalendarForCountry, setMarketSecondaryCalendar } from '../secondaryCalendar';
import { fmtDate } from '../formatters';
import { resolveSecondaryCalendar, usePreferencesStore } from '@/stores/usePreferencesStore';

describe('formatSecondaryDate', () => {
  const d = new Date(Date.UTC(2026, 0, 1, 12));

  it('is empty for none and for an invalid date', () => {
    expect(formatSecondaryDate(d, 'en', 'none')).toBe('');
    expect(formatSecondaryDate(new Date('x'), 'en', 'islamic-umalqura')).toBe('');
  });

  it('prints the Umm al-Qura date', () => {
    // 1 Jan 2026 is 12 Rajab 1447 AH.
    const s = formatSecondaryDate(d, 'en', 'islamic-umalqura', 'UTC');
    expect(s).toMatch(/Rajab/);
    expect(s).toMatch(/1447/);
  });

  it('keeps a locale extension such as a digit system', () => {
    const s = formatSecondaryDate(d, 'ar-SA-u-nu-latn', 'islamic-umalqura', 'UTC');
    expect(s).toMatch(/1447/);
  });
});

describe('resolveSecondaryCalendar', () => {
  it('uses the market only until the user chooses', () => {
    expect(resolveSecondaryCalendar('none', false, null)).toBe('none');
    expect(resolveSecondaryCalendar('none', false, 'islamic-umalqura')).toBe('islamic-umalqura');
    expect(resolveSecondaryCalendar('none', true, 'islamic-umalqura')).toBe('none');
  });

  it('maps Saudi and Gulf countries only', () => {
    expect(secondaryCalendarForCountry('SA')).toBe('islamic-umalqura');
    expect(secondaryCalendarForCountry('de')).toBeNull();
  });
});

describe('fmtDate with a secondary calendar', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    setMarketSecondaryCalendar(null);
    usePreferencesStore.getState().resetPreferences();
  });

  it('is unchanged by default', () => {
    expect(fmtDate('2026-01-01')).not.toMatch(/\(/);
  });

  it('appends the Hijri date when the user chose it', () => {
    usePreferencesStore.getState().setPreferences({ secondaryCalendar: 'islamic-umalqura', secondaryCalendarChosen: true });
    expect(fmtDate('2026-01-01')).toMatch(/\(.*1447.*\)/);
  });

  it('follows the market default and lets the user opt out', () => {
    setMarketSecondaryCalendar('islamic-umalqura');
    expect(fmtDate('2026-01-01')).toMatch(/1447/);
    usePreferencesStore.getState().setPreferences({ secondaryCalendar: 'none', secondaryCalendarChosen: true });
    expect(fmtDate('2026-01-01')).not.toMatch(/1447/);
  });

  it('skips time-only and month-year options', () => {
    usePreferencesStore.getState().setPreferences({ secondaryCalendar: 'islamic-umalqura', secondaryCalendarChosen: true });
    expect(fmtDate('2026-01-01', { month: 'long', year: 'numeric' })).not.toMatch(/\(/);
  });
});
