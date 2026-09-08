// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The one place that answers "which locale does the reader read numbers in".
 *
 * It sits in a leaf module, importing nothing but i18next and React, because
 * the two modules that need the answer would otherwise import each other:
 * `formatters` reads the date-format preference out of the preferences store,
 * and the preferences store has to resolve its number locale from the UI
 * language. Splitting the answer out breaks that cycle, and more usefully
 * leaves exactly one definition to audit.
 */
import { useSyncExternalStore } from 'react';
import i18next from 'i18next';

/**
 * i18next language code → Intl BCP-47 locale tag.
 *
 * Exported so a test can audit THIS map rather than a second copy of it. A
 * census that reconstructs the mapping it is checking proves the two copies
 * agree, not that the shipped one is right.
 */
export const LOCALE_MAP: Record<string, string> = {
  de: 'de-DE',
  da: 'da-DK',
  cs: 'cs-CZ',
  // Plain English claims no region, and the two entries beside it in the
  // picker are how a reader says which one they want: `en-GB` and `en-US` are
  // both offered, so nobody has to work out what unqualified `English` means.
  // This entry used to say `en-US` and was briefly changed to `en-GB`, and
  // both spellings had the same flaw - the map answered a regional question
  // that the reader had not been asked.
  //
  // Self-mapping rather than absent so that the decision is written where the
  // next person looks for it. `LOCALE_MAP[lang] || lang` gives the same string
  // either way, and the contract to pin is `getIntlLocale() === 'en'`, not the
  // shape of this map: an absent key would also be produced by somebody
  // deleting a line, which is not a decision anybody made.
  //
  // What `Intl` does with it, measured rather than assumed (ICU 78): `en`
  // resolves to `en`, prints `3/14/2026` and `$1,234.50`, and starts its week
  // on Sunday - byte for byte what `en-US` prints. CLDR has no region-free
  // English; unqualified `en` inherits the American reading, and `en-001` is
  // the world region rather than no region. So this is neutral in what it
  // claims, not in what it renders, and the honest way to give a reader the
  // British reading is the `en-GB` entry in the picker, not a quiet
  // reinterpretation of the entry they did not qualify.
  en: 'en',
  es: 'es-ES',
  fr: 'fr-FR',
  fi: 'fi-FI',
  hi: 'hi-IN',
  it: 'it-IT',
  ja: 'ja-JP',
  ko: 'ko-KR',
  nl: 'nl-NL',
  no: 'nb-NO',
  pl: 'pl-PL',
  pt: 'pt-BR',
  ru: 'ru-RU',
  sv: 'sv-SE',
  tr: 'tr-TR',
  uk: 'uk-UA',
  bg: 'bg-BG',
  ar: 'ar-SA',
  zh: 'zh-CN',
};

/** Returns the Intl-compatible locale string for the current i18next language. */
export function getIntlLocale(): string {
  const lang = i18next.language || 'en';
  return LOCALE_MAP[lang] || lang;
}

/* ── The same answer, as a subscription ───────────────────────────────────── */

const listeners = new Set<() => void>();
const notify = () => {
  listeners.forEach((cb) => cb());
};

// The default i18next export is the very instance `@/app/i18n` configures and
// re-exports, so this listens to the same language switch the UI performs.
i18next.on('languageChanged', notify);

const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
};

/**
 * `getIntlLocale` for a component that has to re-render when it changes.
 *
 * A plain `getIntlLocale()` call reads i18next once, at render, so a component
 * that reads nothing else keeps the language it first rendered in until some
 * unrelated prop moves it. That is how a money cell is left in the previous
 * language after the picker changes. The snapshot is a string, so React's
 * identity check on it is a value comparison and no caching is needed.
 */
export function useIntlLocale(): string {
  return useSyncExternalStore(subscribe, getIntlLocale, getIntlLocale);
}
