// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
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
