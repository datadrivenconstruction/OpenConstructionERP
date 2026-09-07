// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The one place that answers "in what order does this reader expect names".
 *
 * Sorting text is language-dependent and JavaScript's defaults are not.
 * `['Zebra', 'Ärger'].sort()` puts the umlaut last because it compares UTF-16
 * code units, and a German reader looks for that word under A. Swedish, Danish
 * and Norwegian want the opposite: there Ä and Ö are their own letters at the
 * END of the alphabet, so the German answer is wrong for them and theirs is
 * wrong for German. Czech sorts `ch` as one letter after `h`. Turkish has a
 * dotless i with its own casing. For Chinese a code-unit order is not an order
 * a reader can scan at all.
 *
 * `String.prototype.localeCompare(other)` with no locale argument is only
 * half a fix. It sorts in the RUNTIME's default locale, which in a browser
 * comes from the browser and OS, not from the language this app is set to.
 * A reader who picked Swedish in our language picker while running an English
 * browser gets English collation on Swedish names. This module closes that
 * gap by always naming the locale, and it takes that locale from the same
 * place the rest of the UI does, so there is one answer to audit.
 *
 * Why a cache. `new Intl.Collator(...)` is expensive to construct and a
 * comparator runs O(n log n) times per sort, so building one per comparison
 * (which is what a bare `localeCompare` call inside a sort does) is a real
 * cost on a long list. The collators here are built once per locale and
 * reused, which is both the fast path and the correct one.
 */
import { useMemo } from 'react';

import { getIntlLocale, useIntlLocale } from './intlLocale';

/**
 * Options every user-visible name sort shares.
 *
 * `numeric` is on because our names habitually carry numbers - "Level 2",
 * "Block 10", "Rev 9" - and code-unit order puts "Block 10" before
 * "Block 2". `caseFirst: false` leaves case ranking to the locale rather
 * than forcing upper- or lower-case to the front of every list.
 */
const NAME_COLLATION: Intl.CollatorOptions = { numeric: true, caseFirst: false };

const cache = new Map<string, Intl.Collator>();

/**
 * A collator for the reader's language, built once per locale and reused.
 *
 * Pass a locale to sort in a language other than the one the UI is in - an
 * export rendered for a specific market, say. Omit it and the current UI
 * language is used.
 */
export function getCollator(locale?: string): Intl.Collator {
  const tag = locale ?? getIntlLocale();
  let collator = cache.get(tag);
  if (!collator) {
    // An unknown or malformed tag must not take a list down; fall back to the
    // runtime default, which is still an improvement on code-unit order.
    try {
      collator = new Intl.Collator(tag, NAME_COLLATION);
    } catch {
      collator = new Intl.Collator(undefined, NAME_COLLATION);
    }
    cache.set(tag, collator);
  }
  return collator;
}

/**
 * Compare two user-visible names in the reader's language.
 *
 * This is the drop-in for `a.name.localeCompare(b.name)` inside a sort
 * callback. Null and undefined sort last rather than throwing, because list
 * data routinely carries an unnamed row.
 */
export function compareNames(
  a: string | null | undefined,
  b: string | null | undefined,
  locale?: string,
): number {
  if (a == null || a === '') return b == null || b === '' ? 0 : 1;
  if (b == null || b === '') return -1;
  return getCollator(locale).compare(a, b);
}

/**
 * `compareNames` bound to the current UI language, for a component.
 *
 * A component that calls `compareNames` directly inside a `useMemo` keeps
 * whatever language it first rendered in until some unrelated dependency
 * moves it, which is how a list is left in the previous language after the
 * picker changes. This hook subscribes to the language, so the memo that
 * depends on the returned comparator re-runs on a language switch.
 */
export function useNameCollator(): (
  a: string | null | undefined,
  b: string | null | undefined,
) => number {
  const locale = useIntlLocale();
  return useMemo(() => {
    const collator = getCollator(locale);
    return (a, b) => {
      if (a == null || a === '') return b == null || b === '' ? 0 : 1;
      if (b == null || b === '') return -1;
      return collator.compare(a, b);
    };
  }, [locale]);
}

/** Sort a copy of `values` as user-visible names. Does not mutate the input. */
export function sortNames(values: readonly string[], locale?: string): string[] {
  const collator = getCollator(locale);
  return [...values].sort(collator.compare);
}

/** Test seam: drop the cached collators so a test can change language cleanly. */
export function __resetCollatorCache(): void {
  cache.clear();
}
