// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What to offer a first-run user for the country their browser suggests.
 *
 * Three id-spaces in this product are all called "pack" and none of them
 * shares an identifier with the others:
 *
 *   1. ``packs/<slug>``            real partner packs, served by
 *                                  ``/api/v1/partner-pack/installed``
 *   2. ``backend/app/modules/*_pack``  regional backend modules
 *   3. ``COUNTRY_PACKS``           curated onboarding presets, keyed by a
 *                                  two-letter market id
 *
 * This module joins the first and the third by country, which is the only
 * thing they have in common, and it is deliberately the ONLY place that
 * join is written down.
 *
 * Why a curated preset is a real answer and not a consolation prize: the
 * community wheel deliberately does not ship every pack in this repository.
 * batimatech-ca and bimhessen-de are held back under partnership agreements,
 * so a first-run user in Germany or Canada has no partner pack and never
 * will, however the discovery code is written. Those are two of the markets
 * with the most case studies. Spain has ten cases and no pack at all. So
 * "your country has no pack" is a designed state that a large share of our
 * users land in, not an edge case, and the twenty-one already-translated
 * market presets are what fills it.
 */
import { COUNTRY_PACKS, type CountryPack } from './countryPacks';
import { packCountryCode, type InstalledPartnerPack } from './partnerPacksApi';

/**
 * Curated market ids that are not the ISO 3166-1 alpha-2 code for the
 * country they serve, so a lookup by country has to translate.
 *
 * ``uk`` is the United Kingdom, whose ISO code is GB, and the uk-jct pack
 * tags itself GB. Without this line a British browser matches the pack but
 * not the preset, and the day the pack stops shipping the preset goes
 * unreachable for the country it was written for.
 *
 * There is deliberately no entry mapping Saudi Arabia to the ``ae`` preset.
 * The saudi-vision2030 pack is SA and the curated preset is the United Arab
 * Emirates: two different countries filed under one idea of "Middle East".
 * Offering a UAE preset to a Saudi user because the two are adjacent is the
 * kind of guess this module exists to avoid making.
 */
const PRESET_ID_BY_COUNTRY: Record<string, string> = {
  gb: 'uk',
};

/** What the picker should lead with, or ``null`` when it should lead with nothing. */
export type CountryOffer =
  | { kind: 'pack'; pack: InstalledPartnerPack }
  | { kind: 'preset'; preset: CountryPack };

/**
 * The best thing we can offer for ``country``, or ``null``.
 *
 * A real partner pack beats a curated preset, because it carries the market's
 * cost data, classifications and vocabulary rather than a starting
 * configuration. Beyond that, ``null`` is a first-class answer and the caller
 * must render nothing rather than something: an offer that resolves to a
 * shrug teaches the reader that the feature is noise.
 *
 * @param country lower-case ISO 3166-1 alpha-2, or ``null`` when the browser
 *   said nothing useful.
 * @param packs the packs this deployment actually has. Passed in rather than
 *   read from a hook so a test can feed it the fifteen packs the community
 *   wheel ships instead of the eighteen a checkout has. Germany and Canada
 *   reach the preset branch ONLY under the wheel's fifteen, so a test that
 *   uses whatever the developer's tree happens to hold never executes the
 *   branch that carries the licensing constraint.
 */
export function resolveCountryOffer(
  country: string | null | undefined,
  packs: InstalledPartnerPack[],
): CountryOffer | null {
  if (!country) return null;
  const code = country.toLowerCase();
  // XX is the placeholder a cross-region pack declares to say "no market",
  // and modular-prefab and renewables-epc both use it. Matching on it would
  // hand a vertical pack to a reader as though it were their country's.
  if (code === 'xx') return null;

  const pack = packs.find((p) => packCountryCode(p) === code);
  if (pack) return { kind: 'pack', pack };

  // Never fall through to DEFAULT_COUNTRY_PACK here. It is the first entry of
  // COUNTRY_PACKS, which is the United States, so a country we cannot resolve
  // would silently become a confident offer of the US preset to a reader in
  // Nigeria. "Did not resolve" and "resolved to us" have to stay different
  // answers.
  const presetId = PRESET_ID_BY_COUNTRY[code] ?? code;
  const preset = COUNTRY_PACKS.find((p) => p.id === presetId);
  if (preset) return { kind: 'preset', preset };

  return null;
}

/**
 * The installed pack a pack picker may preselect for ``country``, or ``null``.
 *
 * Only the reader's own country's pack, and only when it is the one pack for
 * that country. The pickers used to fall back to the first pack in the list,
 * which is ordered by slug, so a Canadian first run (no Canadian pack ships)
 * opened with Australia selected and its install button under the thumb. A
 * country served by several packs (the United States has a national one and
 * two for single states) is the reader's choice to make, not the slug
 * order's: preselecting the first made every American a Californian.
 * ``null`` leaves the grid unselected and the curated offer, if any, leads.
 */
export function packToPreselect(
  country: string | null | undefined,
  packs: InstalledPartnerPack[],
): string | null {
  const code = country?.toLowerCase();
  if (!code || code === 'xx') return null;
  const own = packs.filter((p) => packCountryCode(p) === code);
  return own.length === 1 ? (own[0]?.slug ?? null) : null;
}
