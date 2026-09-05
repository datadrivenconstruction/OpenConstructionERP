// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - the market a UI language speaks for, and the ordering that follows.
//
// A language is not a country, and this file exists to keep that sentence true
// rather than to paper over it. Of the languages the product ships, ten reach
// a market the catalogue actually has cases for; the rest reach none, and the
// honest answer for them is the order the catalogue already had.
//
// Nothing here filters. `homeMarketFirst` reorders and returns every case it
// was given, because the alternative - defaulting the market SELECTOR to the
// language - would hide the 140 universal cases from the reader whose language
// happens to name a market, and those cases are the product rather than a
// backlog (see the `region` doc in ./types.ts and the market shelf comment in
// ./CasesPage.tsx). The same "same market first, then the rest, both in
// lifecycle order" shape is already how `moreCasesFor` in ./relatedness.ts
// lays out the strip at the foot of a case, so a reader meets one idea twice
// rather than two.

import { SUPPORTED_LANGUAGES } from '@/app/i18n';

/** A language tag as i18next writes it: lower-case base, upper-case region
 *  subtag, at most two parts. Anything unparseable comes back empty. */
function normalizeLanguageTag(lang: string | null | undefined): string {
  if (!lang) return '';
  const parts = lang.trim().split('-');
  const base = (parts[0] ?? '').toLowerCase();
  if (!base) return '';
  const subtag = parts[1];
  return subtag ? `${base}-${subtag.toUpperCase()}` : base;
}

/**
 * The market a UI language speaks for, or `null` when it speaks for none the
 * catalogue has cases for.
 *
 * `markets` is the set of region codes the catalogue actually carries (the
 * hub's `regions`), so a market with no cases can never become an answer, and
 * a market that gains its first case starts being answered with no edit here.
 *
 * The country comes from `SUPPORTED_LANGUAGES`, where every language already
 * declares one for its flag. That registry is the single place this product
 * says which country a language belongs to, and reusing it means the two can
 * never drift apart. It also settles the sharp cases on its own:
 *
 *   - `es` declares `es`, so Spanish reaches the Spanish cases. `es-MX`,
 *     `es-CL` and `es-CO` declare `mx`, `cl` and `co`, and what each of them
 *     reaches follows the catalogue rather than the language: Mexico has a
 *     case of its own now, so `es-MX` leads with that, while `es-CL` and
 *     `es-CO` still reach none. What none of the three reaches is Spain, and
 *     that is the point rather than a gap: the Spanish cases implement Spanish
 *     public procurement, FIEBDC-3 and Spanish site paperwork, and leading
 *     with them for a Mexican reader would not merely be unhelpful, it would
 *     name a law that does not apply where they work.
 *   - `pt` and `pt-BR` declare `pt` and `br`. Brazil has a case and Portugal
 *     does not, so the two have parted company: `pt-BR` reaches Brazil and
 *     `pt` reaches none. The shape is the same as Spanish; only the counts
 *     differ.
 *   - `en` declares `gb` and `en-US` declares `us`, and the catalogue has both
 *     British and American cases, so the two English entries separate cleanly.
 *
 * A tag the registry does not list is read through its region subtag instead,
 * and the subtag wins outright rather than falling back to the base language's
 * country: `de-AT` and `de-CH` reach no market rather than the German one,
 * `fr-CA` reaches Canada. A bare tag the registry does not list reaches
 * nothing, because a language on its own is not evidence about a country.
 *
 * Note the limit that rule cannot fix from here: `resolveInitialLanguage` in
 * app/i18n.ts strips the region off a browser locale before the app ever sees
 * it, so an Austrian browser arrives as plain `de`. This function will answer
 * `DE` for that reader. That is survivable only because the answer orders the
 * catalogue instead of narrowing it - an Austrian sees the German cases first
 * and every other case right behind them.
 */
export function homeMarketForLanguage(
  lang: string | null | undefined,
  markets: readonly string[],
): string | null {
  const code = normalizeLanguageTag(lang);
  if (!code) return null;
  const declared = SUPPORTED_LANGUAGES.find((l) => l.code === code)?.country;
  const subtag = code.split('-')[1];
  const market = (declared ?? subtag)?.toUpperCase();
  if (!market) return null;
  return markets.includes(market) ? market : null;
}

/**
 * The catalogue in its default order, with the cases for `homeMarket` moved to
 * the front. Both groups keep the order `positionOf` gives them, so the only
 * thing that moves is where the boundary sits.
 *
 * `homeMarket` of `null` is the whole answer for a language that names no
 * market with cases: the list comes back in exactly the order it would have
 * had, which is the catalogue's own lifecycle order (`buildCaseNumbers`:
 * project stage, then the case's `order`, then id). There is no popularity
 * signal in this product to rank cases by, so that order is what "the popular
 * ones" resolves to, and it is named for what it is everywhere it is used.
 */
export function homeMarketFirst<T extends { region?: string }>(
  cases: readonly T[],
  homeMarket: string | null,
  positionOf: (item: T) => number,
): T[] {
  const byPosition = (a: T, b: T) => positionOf(a) - positionOf(b);
  if (!homeMarket) return [...cases].sort(byPosition);
  const home: T[] = [];
  const rest: T[] = [];
  for (const item of cases) {
    (item.region === homeMarket ? home : rest).push(item);
  }
  return [...home.sort(byPosition), ...rest.sort(byPosition)];
}
