// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Secondary calendar: a second date printed next to the Gregorian one.
 *
 * Leaf module (no store import) so the preferences store and the formatters can
 * both use it. The market default lives here as a module variable, for the same
 * reason `marketNumberLocale` does: it is resolved at read time and never
 * written into the stored preference.
 */
import { useSyncExternalStore } from 'react';

export type SecondaryCalendar = 'none' | 'islamic-umalqura';

export const SECONDARY_CALENDARS: readonly SecondaryCalendar[] = ['none', 'islamic-umalqura'];

/** Countries whose documents carry a Hijri date beside the Gregorian one. */
const HIJRI_MARKETS: ReadonlySet<string> = new Set(['sa', 'ae', 'kw', 'qa', 'bh', 'om']);

/** The secondary calendar a country's documents carry, or `null`. */
export function secondaryCalendarForCountry(country: string | null | undefined): SecondaryCalendar | null {
  return HIJRI_MARKETS.has((country || '').trim().toLowerCase()) ? 'islamic-umalqura' : null;
}

let marketCalendar: SecondaryCalendar | null = null;
const listeners = new Set<() => void>();

export function getMarketSecondaryCalendar(): SecondaryCalendar | null {
  return marketCalendar;
}

/** Record (or clear with `null`) the active market's default. No-op when unchanged. */
export function setMarketSecondaryCalendar(value: SecondaryCalendar | null): void {
  if (marketCalendar === value) return;
  marketCalendar = value;
  listeners.forEach((cb) => cb());
}

const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
};

export function useMarketSecondaryCalendar(): SecondaryCalendar | null {
  return useSyncExternalStore(subscribe, getMarketSecondaryCalendar, getMarketSecondaryCalendar);
}

/**
 * The date in the secondary calendar, or `''` when the calendar is `none`, the
 * runtime lacks it, or the date is invalid. Only day/month/year are printed;
 * `timeZone` is honoured so a date-only value pinned to UTC keeps its day.
 */
export function formatSecondaryDate(
  date: Date,
  locale: string | undefined,
  calendar: SecondaryCalendar,
  timeZone?: string,
): string {
  if (calendar === 'none' || Number.isNaN(date.getTime())) return '';
  try {
    const tagged = new Intl.Locale(locale || 'en', { calendar }).toString();
    const fmt = new Intl.DateTimeFormat(tagged, { day: 'numeric', month: 'long', year: 'numeric', timeZone });
    if (fmt.resolvedOptions().calendar !== calendar) return '';
    return fmt.format(date);
  } catch {
    return '';
  }
}
