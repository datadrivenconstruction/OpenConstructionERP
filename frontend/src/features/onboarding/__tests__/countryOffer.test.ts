// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// Tests for resolveCountryOffer: what a first-run picker leads with for the
// country the browser suggests, measured against the pack list the community
// wheel actually ships rather than the one a checkout happens to hold.
import { describe, expect, it } from 'vitest';

import { COUNTRY_PACKS } from '../countryPacks';
import { resolveCountryOffer } from '../countryOffer';
import type { InstalledPartnerPack } from '../partnerPacksApi';

function pack(slug: string, country: string, partnerName: string): InstalledPartnerPack {
  return {
    slug,
    partner_name: partnerName,
    partner_url: null,
    pack_version: '1.0.0',
    description: '',
    default_locale: 'en',
    additional_locales: [],
    cwicr_regions: [],
    default_currency: 'USD',
    default_tax_template: null,
    validation_rule_packs: [],
    default_modules: [],
    hidden_modules: [],
    branding: {} as InstalledPartnerPack['branding'],
    has_onboarding_script: false,
    metadata: { country },
  };
}

/**
 * The twenty-eight packs backend/pyproject.toml force-includes into the
 * community wheel, NOT the thirty a checkout of this repository serves.
 *
 * Thirty and not thirty-one, which is the number of directories under packs/.
 * aus-nzs carries DEPRECATED.txt under src/ and has no manifest.py at all, so
 * the loader never registers it and it is absent from a checkout as much as
 * from a release.
 *
 * The two missing ones are batimatech-ca and doker-formwork
 * (not yet released). bimhessen-de is also checkout-only, so
 * Canada reaches the curated-preset branch on every real install.
 *
 * Keep this list equal to the force-include block.
 */
const WHEEL_PACKS: InstalledPartnerPack[] = [
  pack('aus', 'AU', 'Australia Construction Pack'),
  pack('brazil-sinapi', 'BR', 'Brazil Construction Pack'),
  pack('china-gbt50500', 'CN', 'China Construction Pack'),
  pack('hungary-hu', 'HU', 'Hungary Construction Pack'),
  pack('india-cpwd', 'IN', 'India Construction Pack'),
  pack('mexico-mx', 'MX', 'Mexico Construction Pack'),
  pack('modular-prefab', 'XX', 'Modular & Prefab Pack'),
  pack('nzs', 'NZ', 'New Zealand Construction Pack'),
  pack('renewables-epc', 'XX', 'Renewables EPC Pack'),
  // Declares XX, no single market. Its locale is a bare 'de' with no
  // region subtag, so before it named a country the fallback yielded
  // null and it matched nothing at all.
  pack('retail-grocery-dach', 'XX', 'Discount Grocery Retail (DACH)'),
  pack('russia-gesn', 'RU', 'Russia Construction Pack'),
  pack('saudi-vision2030', 'SA', 'Saudi Vision 2030 Pack'),
  pack('south-africa', 'ZA', 'South Africa Construction Pack'),
  pack('uk-jct', 'GB', 'UK Construction Pack'),
  pack('france-fr', 'FR', 'France Construction Pack'),
  pack('germany-de', 'DE', 'Germany Construction Pack'),
  pack('italy-it', 'IT', 'Italy Construction Pack'),
  pack('japan-jp', 'JP', 'Japan Construction Pack'),
  pack('korea-kr', 'KR', 'South Korea Construction Pack'),
  pack('netherlands-nl', 'NL', 'Netherlands Construction Pack'),
  pack('poland-pl', 'PL', 'Poland Construction Pack'),
  pack('spain-es', 'ES', 'Spain Construction Pack'),
  pack('turkey-tr', 'TR', 'Turkey Construction Pack'),
  pack('uae-ae', 'AE', 'UAE Construction Pack'),
  pack('us-california', 'US', 'California Construction Pack'),
  pack('us-costdata', 'US', 'US Construction Pack'),
  pack('us-texas', 'US', 'Texas Construction Pack'),
];

/** The two the wheel drops for licensing, present only in a checkout. */
const CHECKOUT_ONLY: InstalledPartnerPack[] = [
  pack('batimatech-ca', 'CA', 'Canada Pack'),
  pack('bimhessen-de', 'DE', 'BIM-Cluster Hessen'),
];

describe('resolveCountryOffer, on the packs the wheel ships', () => {
  it('offers the real pack for a country that has one', () => {
    const offer = resolveCountryOffer('br', WHEEL_PACKS);
    expect(offer).toEqual({ kind: 'pack', pack: expect.objectContaining({ slug: 'brazil-sinapi' }) });
  });

  it('offers the pack for Germany now that germany-de ships, and a preset for Canada', () => {
    // Germany now ships germany-de in the wheel; Canada still has no wheel pack.
    expect(resolveCountryOffer('de', WHEEL_PACKS)).toEqual({
      kind: 'pack',
      pack: expect.objectContaining({ slug: 'germany-de' }),
    });
    expect(resolveCountryOffer('ca', WHEEL_PACKS)).toEqual({
      kind: 'preset',
      preset: expect.objectContaining({ id: 'ca' }),
    });
  });

  it('offers the partner pack once it is present alongside the country pack', () => {
    // With batimatech-ca added, Canada resolves to the partner pack.
    // Germany already has germany-de in the wheel; bimhessen-de is the
    // partner variant and the resolver prefers the first match by slug.
    const all = [...WHEEL_PACKS, ...CHECKOUT_ONLY];
    expect(resolveCountryOffer('ca', all)).toEqual({
      kind: 'pack',
      pack: expect.objectContaining({ slug: 'batimatech-ca' }),
    });
  });

  it('offers the pack for Spain now that it ships', () => {
    expect(resolveCountryOffer('es', WHEEL_PACKS)).toEqual({
      kind: 'pack',
      pack: expect.objectContaining({ slug: 'spain-es' }),
    });
  });

  it('translates GB to the uk preset when no British pack is present', () => {
    // The curated ids are not all ISO: the United Kingdom's preset is 'uk'
    // and the pack tags itself GB. With the pack present the pack wins; with
    // it absent the preset has to still be reachable.
    const noBritishPack = WHEEL_PACKS.filter((p) => p.slug !== 'uk-jct');
    expect(resolveCountryOffer('gb', noBritishPack)).toEqual({
      kind: 'preset',
      preset: expect.objectContaining({ id: 'uk' }),
    });
    expect(resolveCountryOffer('gb', WHEEL_PACKS)).toEqual({
      kind: 'pack',
      pack: expect.objectContaining({ slug: 'uk-jct' }),
    });
  });

  it('offers the Hungarian and Russian packs, which the wheel does ship', () => {
    expect(resolveCountryOffer('hu', WHEEL_PACKS)).toEqual({
      kind: 'pack',
      pack: expect.objectContaining({ slug: 'hungary-hu' }),
    });
    expect(resolveCountryOffer('ru', WHEEL_PACKS)).toEqual({
      kind: 'pack',
      pack: expect.objectContaining({ slug: 'russia-gesn' }),
    });

    // Asserted against their own absence, which is how this fixture lost
    // them once already. The two failure modes are not equally visible:
    // Hungary has no curated preset, so a missing hungary-hu falls to null
    // and offers nothing, while Russia has one, so a missing russia-gesn
    // falls to a preset. A plausible confident answer is the harder of the
    // two to notice, and it is the one that looks like success.
    const without = WHEEL_PACKS.filter(
      (p) => p.slug !== 'hungary-hu' && p.slug !== 'russia-gesn',
    );
    expect(resolveCountryOffer('hu', without)).toBeNull();
    expect(resolveCountryOffer('ru', without)?.kind).toBe('preset');
  });

  it('answers null rather than defaulting to the United States', () => {
    // DEFAULT_COUNTRY_PACK is COUNTRY_PACKS[0], the US preset, and reaching
    // for it here would hand a confident American offer to a reader in
    // Nigeria. "Did not resolve" must stay distinguishable from "resolved
    // to us".
    expect(resolveCountryOffer('ng', WHEEL_PACKS)).toBeNull();
    expect(resolveCountryOffer(null, WHEEL_PACKS)).toBeNull();
    expect(resolveCountryOffer(undefined, WHEEL_PACKS)).toBeNull();
    expect(resolveCountryOffer('', WHEEL_PACKS)).toBeNull();
  });

  it('does not offer a Saudi reader the United Arab Emirates', () => {
    // Both are filed under "Middle East" and they are different countries.
    // With the Saudi pack present SA gets its pack; with it absent SA gets
    // its own preset, never 'ae'.
    const noSaudiPack = WHEEL_PACKS.filter((p) => p.slug !== 'saudi-vision2030');
    expect(resolveCountryOffer('sa', noSaudiPack)).toEqual({
      kind: 'preset',
      preset: expect.objectContaining({ id: 'sa' }),
    });
    expect(resolveCountryOffer('sa', WHEEL_PACKS)).toEqual({
      kind: 'pack',
      pack: expect.objectContaining({ slug: 'saudi-vision2030' }),
    });
  });

  it('never matches the XX placeholder country of a cross-region pack', () => {
    // modular-prefab and renewables-epc tag themselves XX because they are
    // not tied to a market. A reader whose browser somehow says 'xx' must
    // not be handed a vertical pack as their country's pack.
    expect(resolveCountryOffer('xx', WHEEL_PACKS)?.kind).not.toBe('pack');
  });

  it('is case-insensitive about the country it is given', () => {
    expect(resolveCountryOffer('BR', WHEEL_PACKS)).toEqual({
      kind: 'pack',
      pack: expect.objectContaining({ slug: 'brazil-sinapi' }),
    });
  });

  it('can answer for every curated market when no pack at all is installed', () => {
    // The fallback is only worth having if it actually covers its own list.
    for (const preset of COUNTRY_PACKS) {
      const country = preset.id === 'uk' ? 'gb' : preset.id;
      expect(resolveCountryOffer(country, [])).toEqual({
        kind: 'preset',
        preset: expect.objectContaining({ id: preset.id }),
      });
    }
  });
});
