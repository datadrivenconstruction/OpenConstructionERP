// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The one place that answers "which date-fns locale does the reader read in".
 *
 * `Intl` needs only a BCP-47 string, so `./intlLocale` can answer for the
 * absolute date branches by handing over a tag. date-fns needs an object: a
 * call that omits `{ locale }` silently falls back to en-US and prints "3
 * hours ago" to a reader who picked German, while the surrounding page and the
 * document language attribute are correct. Nothing goes red, because English
 * is a valid rendering of an English locale. That is why relative timestamps
 * stayed English on the dashboard and the projects list long after every
 * absolute date had been localised.
 *
 * Kept apart from `./intlLocale` because that module is deliberately a leaf
 * importing nothing but i18next and React, and this one pulls in 35 locale
 * objects. Callers that only need a tag should keep using `getIntlLocale`.
 */
import { useSyncExternalStore } from 'react';
import type { Locale } from 'date-fns';
import {
  ar,
  bg,
  bn,
  cs,
  da,
  de,
  el,
  enUS,
  es,
  et,
  faIR,
  fi,
  fr,
  he,
  hi,
  hr,
  id,
  it,
  ja,
  kk,
  ko,
  nb,
  nl,
  pl,
  pt,
  ptBR,
  ro,
  ru,
  sv,
  th,
  tr,
  uk,
  uz,
  vi,
  zhCN,
} from 'date-fns/locale';
import i18next from 'i18next';

/**
 * The three languages date-fns ships no locale for.
 *
 * Named here rather than left to the fallback so the gap is a decision with a
 * list, not an absence. The test beside this file asserts in both directions:
 * these three must resolve to en-US, and every other language must not.
 * If date-fns adds one of them the test goes red and the entry moves up into
 * the map, which is the only way we would find out.
 */
export const LANGUAGES_WITHOUT_DATE_FNS_LOCALE = ['fil', 'ky', 'ur'] as const;

/**
 * i18next language code → date-fns `Locale`.
 *
 * Keyed by the exact code first so the regional Portuguese and English
 * variants land on their own locale, then by base language, so `es-MX` and
 * `es-CO` reach `es` without three more identical entries. Norwegian is the
 * one pair whose two sides are spelled differently on purpose: our language
 * code is `no` and date-fns publishes Bokmål as `nb`.
 */
const DATE_FNS_LOCALE_MAP: Record<string, Locale> = {
  ar,
  bg,
  bn,
  cs,
  da,
  de,
  el,
  en: enUS,
  'en-US': enUS,
  es,
  et,
  fa: faIR,
  fi,
  fr,
  he,
  hi,
  hr,
  id,
  it,
  ja,
  kk,
  ko,
  nl,
  no: nb,
  pl,
  pt,
  'pt-BR': ptBR,
  ro,
  ru,
  sv,
  th,
  tr,
  uk,
  uz,
  vi,
  zh: zhCN,
};

/** Returns the date-fns locale for an explicit i18next language code. */
export function dateFnsLocaleFor(lang: string | null | undefined): Locale {
  if (!lang) return enUS;
  const exact = DATE_FNS_LOCALE_MAP[lang];
  if (exact) return exact;
  const base = lang.split('-')[0];
  return (base ? DATE_FNS_LOCALE_MAP[base] : undefined) ?? enUS;
}

/** Returns the date-fns locale for the language the reader is currently in. */
export function getDateFnsLocale(): Locale {
  return dateFnsLocaleFor(i18next.language);
}

/* ── The same answer, as a subscription ───────────────────────────────────── */

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

/**
 * `getDateFnsLocale` for a component that has to re-render when it changes.
 *
 * Same reason `useIntlLocale` exists next to `getIntlLocale`: a component that
 * reads the language once at render keeps it until some unrelated prop moves
 * it, which is how a month header is left in the previous language after the
 * picker changes. The snapshot is one of the module-level locale objects, so
 * its identity is stable for a given language and React's check on it holds
 * without any caching here.
 */
export function useDateFnsLocale(): Locale {
  return useSyncExternalStore(subscribe, getDateFnsLocale, getDateFnsLocale);
}
