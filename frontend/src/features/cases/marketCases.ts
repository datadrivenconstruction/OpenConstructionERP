// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - the market a reader works in, resolved for the dashboard.
//
// `homeMarket.ts` answers one question: which market a UI LANGUAGE speaks for.
// The dashboard card that leads with a reader's own market asks a wider one,
// because the product knows two more things about where a reader works: the
// regional pack they applied, and, for a language whose own country has no
// cases, the market a reader of that language most likely borrows from. This
// file layers those two AROUND the language answer rather than beside it, so
// the catalogue and the card can never disagree about what a language means:
// the language step here IS `homeMarketForLanguage`, imported, not copied,
// and the ordering inside a market IS `homeMarketFirst`.
//
// Three sources, in order of how much they say about the reader:
//
//   pack      - the applied regional pack names a country and the catalogue
//               has cases for it. Someone who switched on the Texas pack has
//               said where they work more plainly than a UI language ever
//               could, and a German-speaking estimator on a US pack is not a
//               rare shape.
//   language  - `homeMarketForLanguage`: the country the language registry
//               declares, only when the catalogue carries cases for it.
//   nearest   - `NEAREST_MARKETS_BY_LANGUAGE`: for a language whose declared
//               country has no cases, the markets its readers most often work
//               to, tried in order. This is a SUGGESTION and the card words it
//               as one: a Chilean reader is offered the Spanish cases as the
//               closest thing in their language, never told that Spain is
//               their market. The catalogue deliberately does not take this
//               step. It orders 220 cases rather than picking one market, and
//               there a guess would hide nothing but would also help nobody.
//
// Nothing here filters or writes. The card that consumes it keeps every market
// one click away, and the reader's stored market pick on the hub
// (`oe_cases_region`) is never touched by any of this.

import { marketCode } from '@/shared/lib/regionalPack';

import { homeMarketFirst, homeMarketForLanguage, normalizeLanguageTag } from './homeMarket';

/** Where a home market came from. */
export type HomeMarketSource = 'pack' | 'language' | 'nearest';

export interface HomeMarketResolution {
  /** ISO 3166-1 alpha-2, upper case as the cases spell it, or null. */
  market: string | null;
  /** Which source answered, or null when none could. */
  source: HomeMarketSource | null;
}

/**
 * Markets to offer a language whose own country has no cases, in order.
 *
 * Keyed by the tag as `normalizeLanguageTag` writes it. A regional tag is
 * looked up exactly and then by its base language, so `es-CL` is answered by
 * its own row and `fr-CA` by the French one. A row only ever matters AFTER the
 * language step has answered null, which is why `pt-BR` and `en-US` need no
 * entry: the registry already declares Brazil and the United States for them.
 *
 * Every candidate is checked against the catalogue before it is used, so a
 * market that loses its last case drops out of the answer with no edit here,
 * and a market listed here that has no cases is a harmless row, not a wrong
 * answer.
 */
export const NEAREST_MARKETS_BY_LANGUAGE: Readonly<Record<string, readonly string[]>> = {
  // Spanish outside Spain: the Spanish cases are the closest in language and
  // the Mexican case the closest in law. Both are offered, in that order, and
  // the card says "closest", never "yours".
  'es-CL': ['ES', 'MX'],
  'es-CO': ['ES', 'MX'],
  // Portugal has no cases and Brazil has. The two Portuguese entries already
  // part company in the language step (`pt-BR` declares Brazil), so this row
  // only ever answers for plain `pt`.
  pt: ['BR'],
  // The registry declares France for French, and France has no cases. The
  // Canadian cases are written for a market whose paperwork exists in French.
  fr: ['CA'],
  // Bengali declares Bangladesh; the Indian cases are the nearest market.
  bn: ['IN'],
  // Hungarian is on disk and not yet offered, so the registry declares no
  // country for it. This row keeps the Hungarian case reachable meanwhile and
  // becomes redundant, not wrong, the day the language is registered.
  hu: ['HU'],
  // English: the registry already answers Britain for `en` and the United
  // States for `en-US`, so this row is consulted only if those cases were ever
  // gone. It exists so that "no British cases" degrades to the next English-
  // speaking market instead of to nothing.
  en: ['US', 'GB', 'CA', 'AU', 'NZ', 'IN', 'ZA'],
};

/** The nearest-market candidates for a language, or an empty list. */
export function nearestMarketsForLanguage(lang: string | null | undefined): readonly string[] {
  const code = normalizeLanguageTag(lang);
  if (!code) return [];
  const exact = NEAREST_MARKETS_BY_LANGUAGE[code];
  if (exact) return exact;
  const base = code.split('-')[0] ?? '';
  return NEAREST_MARKETS_BY_LANGUAGE[base] ?? [];
}

export interface ResolveHomeMarketInput {
  /** The UI language as i18next reports it. */
  language: string | null | undefined;
  /** Country of the applied regional pack as `packCountryCode` spells it (lower
   *  case); `xx`, `all`, empty and null all mean "no single market". */
  packCountry?: string | null;
  /** The markets the catalogue actually has cases for, upper case. */
  markets: readonly string[];
}

/**
 * The reader's home market and where that answer came from.
 *
 * Pack first, then language, then the nearest-market table, each step only
 * answering with a market in `markets`. A pack for a country with no cases is
 * skipped rather than shown empty: the card exists to show cases, and a pack
 * that names a market the catalogue has nothing for says nothing useful here.
 */
export function resolveHomeMarket({
  language,
  packCountry,
  markets,
}: ResolveHomeMarketInput): HomeMarketResolution {
  const pack = marketCode(packCountry)?.toUpperCase();
  if (pack && markets.includes(pack)) return { market: pack, source: 'pack' };

  const spoken = homeMarketForLanguage(language, markets);
  if (spoken) return { market: spoken, source: 'language' };

  for (const candidate of nearestMarketsForLanguage(language)) {
    if (markets.includes(candidate)) return { market: candidate, source: 'nearest' };
  }
  return { market: null, source: null };
}

/** One market on the shelf: its code and how many cases carry it. */
export interface MarketShelfEntry {
  market: string;
  count: number;
}

/** How many cases each market has. Universal cases (no `region`) are not
 *  counted anywhere: they are the catalogue's own shelf, not a market's. */
export function countCasesByMarket<T extends { region?: string }>(
  cases: readonly T[],
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of cases) {
    if (!item.region) continue;
    counts.set(item.region, (counts.get(item.region) ?? 0) + 1);
  }
  return counts;
}

/**
 * The market shelf in reading order: the home market first, then the rest by
 * how many cases they hold, ties broken by code so the order is stable across
 * renders and languages. A `homeMarket` that is not on the shelf (or null)
 * leaves the whole list ordered by count.
 */
export function orderMarkets(
  counts: ReadonlyMap<string, number>,
  homeMarket: string | null,
): MarketShelfEntry[] {
  return [...counts.entries()]
    .map(([market, count]) => ({ market, count }))
    .sort((a, b) => {
      if (a.market === homeMarket) return -1;
      if (b.market === homeMarket) return 1;
      return b.count - a.count || a.market.localeCompare(b.market);
    });
}

/**
 * The cases written for one market, in the order the catalogue gives them.
 *
 * Goes through `homeMarketFirst` rather than a bare filter so the order inside
 * the market is the SAME order the hub shows when it leads with that market:
 * one helper decides what "first" means in both places.
 */
export function casesForMarket<T extends { region?: string }>(
  cases: readonly T[],
  market: string | null,
  positionOf: (item: T) => number,
): T[] {
  if (!market) return [];
  return homeMarketFirst(cases, market, positionOf).filter((item) => item.region === market);
}
