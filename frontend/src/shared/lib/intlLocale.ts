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
  hu: 'hu-HU',
  it: 'it-IT',
  ja: 'ja-JP',
  ko: 'ko-KR',
  nl: 'nl-NL',
  no: 'nb-NO',
  pl: 'pl-PL',
  // `pt` is the European entry in the picker; Brazil has its own `pt-BR`
  // entry, which reaches Intl unchanged. Mapping `pt` to Brazil printed
  // Lisbon's dates and numbers the Brazilian way.
  pt: 'pt-PT',
  ru: 'ru-RU',
  sv: 'sv-SE',
  tr: 'tr-TR',
  uk: 'uk-UA',
  bg: 'bg-BG',
  ar: 'ar-SA',
  zh: 'zh-CN',
};

/* ── Digit shapes ──────────────────────────────────────────────────────────── */

/**
 * Which digits the reader wants, as a CLDR numbering system, or `'auto'` for
 * whatever the locale prints.
 *
 * Separate from the locale because it is a separate question. Arabic prints
 * Arabic-Indic digits by default, while Egyptian business documents commonly
 * use Western ones; a Persian reader writes a third set. The preference store
 * owns the value and pushes it here, the same way the market's number locale
 * is pushed into `marketNumberLocale`, because this module is a leaf and the
 * store imports it.
 */
export type DigitSystem = 'auto' | 'latn' | 'arab' | 'arabext';

/** Every value `DigitSystem` may hold, for pickers and for validating server values. */
export const DIGIT_SYSTEMS: readonly DigitSystem[] = ['auto', 'latn', 'arab', 'arabext'];

let digitSystem: DigitSystem = 'auto';

/**
 * `tag` written in `digits`, as the BCP-47 `-u-nu-` extension `Intl` reads.
 *
 * Returns `tag` untouched for `'auto'` and when the locale already prints that
 * system, so an English reader who asks for Western digits keeps the plain
 * `en` every other check in the product compares against. Idempotent: a tag
 * that already carries the extension resolves to the asked system and comes
 * back as it is.
 */
export function withDigitSystem(tag: string, digits: DigitSystem = digitSystem): string {
  if (digits === 'auto') return tag;
  try {
    if (new Intl.NumberFormat(tag).resolvedOptions().numberingSystem === digits) return tag;
    const bare = tag.replace(/-nu-[a-z0-9]+/i, '').replace(/-u$/i, '');
    const extended = /-u-/i.test(bare) ? `${bare}-nu-${digits}` : `${bare}-u-nu-${digits}`;
    return new Intl.NumberFormat(extended).resolvedOptions().numberingSystem === digits ? extended : tag;
  } catch {
    return tag;
  }
}

/** The digit system currently in force. */
export function getDigitSystem(): DigitSystem {
  return digitSystem;
}

/**
 * Record the reader's digit system. Called by the preferences store whenever
 * its value changes. A no-op when nothing changed, so it does not wake every
 * surface on an unrelated preference write.
 */
export function setDigitSystem(next: DigitSystem): void {
  const value = DIGIT_SYSTEMS.includes(next) ? next : 'auto';
  if (value === digitSystem) return;
  digitSystem = value;
  notify();
}

/** Returns the Intl-compatible locale string for the current i18next language. */
export function getIntlLocale(): string {
  const lang = i18next.language || 'en';
  return withDigitSystem(LOCALE_MAP[lang] || lang);
}

/* ── The same answer, as a subscription ───────────────────────────────────── */

const listeners = new Set<() => void>();
function notify(): void {
  listeners.forEach((cb) => cb());
}

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
