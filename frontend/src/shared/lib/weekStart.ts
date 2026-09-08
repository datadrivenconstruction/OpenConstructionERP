// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The one place that answers "which day does the reader's week start on".
 *
 * Four features used to answer it separately and three of them answered
 * Monday unconditionally, so a calendar rendered the same grid for all 42
 * offered languages. The fourth read the real value out of `Intl` and then
 * threw most of it away: it collapsed the answer to `firstDay === 7 ? 0 : 1`,
 * which is right for the 40 languages that start on Monday or Sunday and
 * wrong for the two that start on Saturday. Arabic and Persian got Monday,
 * a day their working week does not begin on.
 *
 * Two numbering conventions meet here and mixing them is how that defect
 * comes back, so each has a name and the conversion is one exported
 * function rather than an inline `? :` at a call site:
 *
 *   - CLDR / `Intl` `firstDay`: 1 = Monday through 7 = Sunday. Never 0.
 *   - JavaScript `Date#getDay()` and date-fns `weekStartsOn`: 0 = Sunday
 *     through 6 = Saturday.
 *
 * `weekStartFor` speaks CLDR because that is what the data source speaks.
 * Call sites want `weekStartsOnFor`, which converts at the boundary.
 *
 * This module is deliberately a leaf, in the same sense and for the same
 * reason as `./intlLocale`: `weekStartFor` imports nothing at all, so a test
 * can bundle and run the shipped function on its own. Only the two
 * "current language" wrappers at the bottom pull in i18next and React.
 */
import { useSyncExternalStore } from 'react';
import i18next from 'i18next';

/** CLDR first day of week: 1 = Monday through 7 = Sunday. Never 0. */
export type CldrFirstDay = 1 | 2 | 3 | 4 | 5 | 6 | 7;

/** `Date#getDay()` and date-fns `weekStartsOn`: 0 = Sunday through 6 = Saturday. */
export type WeekStartsOn = 0 | 1 | 2 | 3 | 4 | 5 | 6;

/**
 * First day of the week per language, for engines with no `weekInfo`.
 *
 * The map that used to sit inside `localeWeekStart` listed Arabic as
 * Sunday-first while the `Intl` path above it answered Monday and the truth
 * is Saturday. It was unreachable on every engine that implements
 * `weekInfo`, so nothing ever contradicted it: three answers for one
 * language and no way to notice. This table is exported so
 * `weekStart.test.ts` can assert it agrees with ICU for every offered
 * language, which turns it from documentation of an intent into a checked
 * copy. Anything absent starts on Monday, the majority answer.
 *
 * Keys are matched whole first, then by base language, so `es-MX` can differ
 * from `es` while `pt-BR` inherits `pt`.
 */
export const FALLBACK_FIRST_DAY: Readonly<Record<string, CldrFirstDay>> = {
  // Saturday-first.
  ar: 6,
  fa: 6,
  // Sunday-first.
  en: 7,
  'es-MX': 7,
  'es-CO': 7,
  pt: 7,
  hi: 7,
  ja: 7,
  ko: 7,
  id: 7,
  th: 7,
  bn: 7,
  fil: 7,
  ur: 7,
  he: 7,
  // Monday-first, and named rather than left to inherit, because its base
  // answers differently. Britain starts its week on Monday where unqualified
  // English is Sunday-first, so `en-GB` falling through to the `en` above
  // would put this table a day away from the `Intl` path on the reader who
  // picked English (UK) precisely to get the British reading.
  'en-GB': 1,
};

/**
 * The reader's first day of the week, as CLDR numbers it.
 *
 * Reads both spellings of the same data on purpose. `weekInfo` shipped as a
 * property and was later respecified as a `getWeekInfo()` method, so a
 * browser may have either one. Reading only the one this Node happens to
 * have would send every other engine down the fallback and quietly answer
 * Monday for the whole world.
 */
export function weekStartFor(locale: string | undefined | null): CldrFirstDay {
  const tag = locale || 'en';
  try {
    const loc = new Intl.Locale(tag) as Intl.Locale & {
      getWeekInfo?: () => { firstDay?: number };
      weekInfo?: { firstDay?: number };
    };
    const info = typeof loc.getWeekInfo === 'function' ? loc.getWeekInfo() : loc.weekInfo;
    const first = info?.firstDay;
    if (typeof first === 'number' && first >= 1 && first <= 7) {
      return first as CldrFirstDay;
    }
  } catch {
    /* Malformed tag, or an engine with no week data. Fall through. */
  }
  const exact = FALLBACK_FIRST_DAY[tag];
  if (exact) return exact;
  const base = tag.split('-')[0] ?? '';
  return FALLBACK_FIRST_DAY[base] ?? 1;
}

/** CLDR 1..7 to the 0..6 index `getDay()` and date-fns use. Sunday is 7 there and 0 here. */
export function toWeekStartsOn(firstDay: CldrFirstDay): WeekStartsOn {
  return (firstDay === 7 ? 0 : firstDay) as WeekStartsOn;
}

/** The reader's first day of the week, ready to hand to date-fns or compare with `getDay()`. */
export function weekStartsOnFor(locale: string | undefined | null): WeekStartsOn {
  return toWeekStartsOn(weekStartFor(locale));
}

/* ── The same answer for the current UI language ──────────────────────────── */

const listeners = new Set<() => void>();
i18next.on('languageChanged', () => {
  listeners.forEach((cb) => cb());
});

const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
};

/** First day of the week for the language the UI is in right now. */
export function getWeekStartsOn(): WeekStartsOn {
  return weekStartsOnFor(i18next.language);
}

/**
 * `getWeekStartsOn` for a component that has to re-render when it changes.
 *
 * Same reason `useIntlLocale` and `useDateFnsLocale` exist beside their plain
 * getters: a component that reads the language once at render keeps it until
 * some unrelated prop moves it, which would leave a month grid rotated for
 * the previous language after the picker changes. The snapshot is a number,
 * so React's identity check on it is a value comparison.
 */
export function useWeekStartsOn(): WeekStartsOn {
  return useSyncExternalStore(subscribe, getWeekStartsOn, getWeekStartsOn);
}
