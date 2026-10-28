// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The two facts about a regional pack that more than one feature needs.
 *
 * Which country a pack serves, and which language it speaks, are asked by the
 * onboarding picker, by the dashboard card that names the active pack, and by
 * a case that wants to say which pack covers its market. Features in this
 * codebase do not import from each other - measured, there is not one
 * `@/features/x` import inside another feature - so the join has to live in
 * `shared` or be written three times. It was already written once in
 * `features/onboarding/partnerPacksApi.ts`, which now re-exports from here so
 * there is exactly one copy rather than a second that drifts.
 *
 * Deliberately NOT here: anything that needs the curated `COUNTRY_PACKS`
 * presets. Those are onboarding's own data and the offer logic that reads them
 * stays in `features/onboarding/countryOffer.ts`.
 */

/**
 * The subset of a pack that this module reads.
 *
 * Both `InstalledPartnerPack` (the onboarding list) and `PartnerPackManifest`
 * (the active-pack hook) satisfy it, which is the point: they are two names
 * for the same backend payload, and a caller should not have to know which one
 * it is holding to ask which country a pack is for.
 */
export interface RegionalPackFacts {
  slug: string;
  partner_name: string;
  default_locale: string;
  metadata: Record<string, unknown>;
}

/**
 * ISO 3166-1 alpha-2 for the country a pack serves, lower case, or `null`.
 *
 * Prefers `metadata.country` (every reference pack sets it), then the region
 * subtag of `default_locale` (`fr-CA` -> `ca`). `null` when neither says, so
 * the caller renders a generic glyph rather than a wrong flag.
 *
 * Note that `XX` is a real value here: it is the placeholder a cross-region
 * pack declares to mean "no single market", and modular-prefab and
 * renewables-epc both use it. This function reports it as `'xx'` rather than
 * `null` because it IS what the pack said; callers that are matching a country
 * have to exclude it themselves, and `resolveCountryOffer` does.
 */
export function packCountryCode(pack: RegionalPackFacts): string | null {
  const metaCountry = pack.metadata?.country;
  if (typeof metaCountry === 'string' && metaCountry.length === 2) {
    return metaCountry.toLowerCase();
  }
  const region = pack.default_locale.split('-')[1];
  if (region && region.length === 2) {
    return region.toLowerCase();
  }
  return null;
}

/**
 * A pack's slug, spelled the way the `modules.pp_name_*` i18n family spells it.
 *
 * There is deliberately no `packNameKey(slug)` helper next to this, and the
 * three call sites all write the key out as
 * `t(\`modules.pp_name_${packNameSlug(pack.slug)}\`, { defaultValue: ... })`
 * with the template literal inline. `scripts/check_i18n_computed_keys.py`
 * recognises a computed key ONLY in that exact shape; a helper returning the
 * finished key would move it one function hop away, and the gate would then
 * report nothing at all for a family of fifteen names missing from forty-one
 * languages. The tidier version is the one that buys silence.
 *
 * What those names replaced: `metadata.country_name_en`, a field whose name is
 * literal. It is English, it is only ever English, and us-california,
 * us-costdata and us-texas all carry the same "United States" in it, so three
 * tiles showed one word between them while their real names sat unread.
 */
export function packNameSlug(slug: string): string {
  return slug.replace(/-/g, '_');
}

/**
 * The one line of a pack's description worth showing on a card.
 *
 * Every shipped pack writes its description the same way: a clause naming who
 * the pack is for, a colon, then the list of what it carries. "Pre-configured
 * for UK general contractors: RICS NRM 1+2 (2nd ed, 2021) with optional NRM 3
 * ...". The clause before the colon is the answer to "is this mine", and the
 * list after it is detail nobody reads from a grid of eighteen cards.
 *
 * Measured against the eighteen packs on disk, that clause runs 39 to 81
 * characters and every one of them reads as a sentence. Clamping the full text
 * with CSS instead would cut mid-list at a different point on every card,
 * which is what a wall of eighteen ragged paragraphs looked like.
 *
 * A description with no colon, or one whose head is too long to be a summary,
 * falls back to the whole text: a bad guess at brevity is worse than the
 * paragraph, because the reader cannot tell that anything was dropped.
 */
export function packSummary(description: string | null | undefined): string {
  const text = (description ?? '').trim();
  if (!text) return '';
  const head = text.split(':')[0]?.trim() ?? '';
  if (head.length >= 12 && head.length <= 95 && head.length < text.length) return head;
  return text;
}

/**
 * The market a case names, normalised, or `null` when it names none.
 *
 * Three spellings mean "this case belongs to no single market" and they have
 * to collapse to one answer: absent, `xx`, which is a pack's own word for
 * cross-region and which a case must never match against, and `all`. Every
 * caller that asks "does this case have a market" has to agree with the
 * resolver about the answer, because one of them offers a pack and the other
 * explains why there is none, and the two disagreeing would put both on the
 * same screen or neither.
 */
export function marketCode(region: string | null | undefined): string | null {
  const wanted = region?.trim().toLowerCase();
  if (!wanted || wanted === 'xx' || wanted === 'all') return null;
  return wanted;
}

/**
 * A market's packs, split by whether one of them is the applied pack.
 *
 * Three states have to be told apart and the obvious source tells apart only
 * two of them. ``GET /partner-pack/installed`` is named for installation but
 * returns every pack discovered on disk - eighteen here, with `active_slug`
 * null - so a caller reading only that list sees "installed" and offers no
 * action, while a caller reading only ``/current`` sees "no pack" and cannot
 * name the one that would serve the market. The three states a reader in front
 * of a German case actually has are: a German pack is applied, a German pack is
 * on disk and switched off, or there is no German pack at all. `active_slug`,
 * which the same envelope already carries, is what separates the first two.
 *
 * The applied pack sorts first because it is the answer to "what am I looking
 * at", and the rest follow as alternatives. Several packs can serve one market
 * - us-california, us-costdata and us-texas all declare US - so this is a list
 * and not a lookup.
 *
 * `region` is compared case-insensitively: cases spell it `DE` and packs spell
 * it `de`, and both spellings are correct in their own file.
 */
export function resolveMarketPacks<T extends RegionalPackFacts>(
  installed: readonly T[],
  activeSlug: string | null | undefined,
  region: string | null | undefined,
): { packs: T[]; applied: T | null } {
  const wanted = marketCode(region);
  if (!wanted) return { packs: [], applied: null };

  const packs = installed.filter((p) => packCountryCode(p) === wanted);
  const applied = packs.find((p) => p.slug === activeSlug) ?? null;
  if (!applied) return { packs, applied: null };
  return { packs: [applied, ...packs.filter((p) => p !== applied)], applied };
}

/**
 * The bands packs are offered in, most important first.
 *
 * Until now the packs page listed whatever `GET /partner-pack/installed`
 * returned, and that endpoint sorts by slug because a lookup wants a stable
 * order, not a persuasive one. Forty-three cards alphabetised by slug put
 * `aus` first, `batimatech-ca` between Austria and Belgium because the sort
 * never sees the display name, and the United States at the very bottom. A
 * reader scanning that grid learns nothing about which pack matters to them.
 *
 * The order here is by construction market, largest first, which is the same
 * order the industry itself uses when it sizes these markets: the United
 * States, China, India, then Europe in aggregate. Everything else follows.
 * The bands are deliberately coarse, because a finer ranking would be a claim
 * we cannot support and would need re-litigating every year.
 *
 * `home` sits above all of them. A reader in Poland is not served by seeing
 * the United States first, however large that market is, and the whole point
 * of a country pack is that it carries the reader's own standards.
 *
 * Why Turkey and Russia are not in `europe`: the band is a standards family,
 * not a landmass. `europe` is the EN/Eurocode world plus the United Kingdom,
 * which is what makes those packs substitutable enough to sit together in one
 * group. Turkey prices against TS and Russia against GESN, so grouping either
 * under a European heading would tell a reader something untrue about what
 * the pack contains. Both land in `rest`, which claims nothing.
 */
export const PACK_MARKET_BANDS = [
  'home',
  'americas',
  'china',
  'india',
  'europe',
  'rest',
  'cross-region',
] as const;

/** One of {@link PACK_MARKET_BANDS}. */
export type PackMarketBand = (typeof PACK_MARKET_BANDS)[number];

/**
 * ISO 3166-1 alpha-2 for the Americas, north to south including the Caribbean.
 *
 * Written out in full rather than as the four countries we ship packs for, so
 * a Chilean or Colombian pack added later lands in the right band without
 * anyone remembering this file exists. The same reasoning applies to
 * {@link EUROPE_COUNTRIES}.
 */
const AMERICAS_COUNTRIES = new Set([
  'ag', 'ar', 'bb', 'bo', 'br', 'bs', 'bz', 'ca', 'cl', 'co', 'cr', 'cu',
  'dm', 'do', 'ec', 'gd', 'gt', 'gy', 'hn', 'ht', 'jm', 'kn', 'lc', 'mx',
  'ni', 'pa', 'pe', 'py', 'sr', 'sv', 'tt', 'us', 'uy', 'vc', 've',
]);

/** ISO 3166-1 alpha-2 for the EN/Eurocode standards family plus the UK. */
const EUROPE_COUNTRIES = new Set([
  'ad', 'al', 'at', 'ba', 'be', 'bg', 'ch', 'cy', 'cz', 'de', 'dk', 'ee',
  'es', 'fi', 'fr', 'gb', 'gr', 'hr', 'hu', 'ie', 'is', 'it', 'li', 'lt',
  'lu', 'lv', 'mc', 'md', 'me', 'mk', 'mt', 'nl', 'no', 'pl', 'pt', 'ro',
  'rs', 'se', 'si', 'sk', 'sm', 'ua', 'xk',
]);

/**
 * Which band a pack belongs to, given the country the reader is probably in.
 *
 * `homeCountry` is the browser's guess from `detectCountry`, so it is a hint
 * and never a gate: the only thing it changes is which card is drawn first.
 * `xx` is excluded from matching it for the same reason `resolveCountryOffer`
 * excludes it - it is a pack's own word for "no single market", and a reader
 * whose browser somehow said `xx` must not be handed a vertical pack as
 * though it were their country's.
 *
 * A pack that names no country at all is cross-region too. `doker-formwork`
 * is the live example: an industry pack with a bare `de` locale that carries
 * no region subtag, so {@link packCountryCode} reports `null` for it, which is
 * the honest answer and not a defect.
 */
export function packMarketBand(
  pack: RegionalPackFacts,
  homeCountry?: string | null,
): PackMarketBand {
  const code = packCountryCode(pack);
  if (code === null || code === 'xx') return 'cross-region';

  const home = homeCountry?.trim().toLowerCase();
  if (home && home !== 'xx' && home === code) return 'home';

  if (AMERICAS_COUNTRIES.has(code)) return 'americas';
  if (code === 'cn') return 'china';
  if (code === 'in') return 'india';
  if (EUROPE_COUNTRIES.has(code)) return 'europe';
  return 'rest';
}

/** Position of a pack's band in {@link PACK_MARKET_BANDS}; lower sorts first. */
export function packMarketRank(
  pack: RegionalPackFacts,
  homeCountry?: string | null,
): number {
  return PACK_MARKET_BANDS.indexOf(packMarketBand(pack, homeCountry));
}

/**
 * Packs in the order a reader should meet them.
 *
 * Band first, then the pack's display name inside the band. The name has to
 * come from the caller rather than from `partner_name`, because what the card
 * shows is the translated `modules.pp_name_*` string and sorting on anything
 * else would order the grid by a name nobody on screen can see. For the same
 * reason the comparison runs through `Intl.Collator` at the reader's own
 * locale: `Ö` belongs after `O` for a German reader and after `Z` for a
 * Swedish one, and a plain `<` gets both wrong.
 *
 * Returns a new array; the input is not mutated, because it is a React Query
 * cache entry and sorting it in place would reorder every other consumer's
 * copy of the same object.
 */
export interface PackOrderOptions<T extends RegionalPackFacts> {
  /** Lower-case ISO 3166-1 alpha-2 from `detectCountry`, or null. */
  homeCountry?: string | null;
  /** The name the card actually renders for this pack. */
  nameOf: (pack: T) => string;
  /** BCP 47 tag for the collation; defaults to the runtime's own locale. */
  locale?: string;
}

export function sortPacksByMarket<T extends RegionalPackFacts>(
  packs: readonly T[],
  options: PackOrderOptions<T>,
): T[] {
  const { homeCountry = null, nameOf, locale } = options;
  const collator = new Intl.Collator(locale, { sensitivity: 'base', numeric: true });
  return [...packs].sort((a, b) => {
    const rankDelta = packMarketRank(a, homeCountry) - packMarketRank(b, homeCountry);
    if (rankDelta !== 0) return rankDelta;
    return collator.compare(nameOf(a), nameOf(b));
  });
}

/**
 * The packs of each band, in band order, with empty bands dropped.
 *
 * The page renders a heading per band, and a heading over nothing reads as a
 * loading state or a bug. Dropping empty bands here rather than in the markup
 * keeps that decision in one place and lets a test assert it.
 */
export function groupPacksByMarket<T extends RegionalPackFacts>(
  packs: readonly T[],
  options: PackOrderOptions<T>,
): { band: PackMarketBand; packs: T[] }[] {
  const ordered = sortPacksByMarket(packs, options);
  const home = options.homeCountry ?? null;
  return PACK_MARKET_BANDS.map((band) => ({
    band,
    packs: ordered.filter((p) => packMarketBand(p, home) === band),
  })).filter((group) => group.packs.length > 0);
}
