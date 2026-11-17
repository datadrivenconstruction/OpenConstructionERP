// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, it, expect } from 'vitest';
import { packCountryCode, packOutsideMarkets, packSummary, resolveMarketPacks } from './regionalPack';

function pack(slug: string, country: string | null, locale = 'en-US') {
  return {
    slug,
    partner_name: slug,
    default_locale: locale,
    metadata: country === null ? {} : { country },
  };
}

/* The list this suite reasons about is the one the deployment actually serves:
 * eighteen packs discovered on disk with no pack applied. Both facts are
 * measured rather than assumed, because they are what makes the third state
 * below reachable at all. */
const INSTALLED = [
  pack('bimhessen-de', 'DE'),
  pack('uk-jct', 'GB'),
  pack('us-california', 'US'),
  pack('us-costdata', 'US'),
  pack('us-texas', 'US'),
  pack('china-gbt50500', 'CN'),
  pack('modular-prefab', 'XX'),
  pack('doker-formwork', null, 'en'),
];

describe('resolveMarketPacks', () => {
  it('matches a case spelling its market DE against a pack spelling it de', () => {
    // The two spellings live in different files and each is correct there, so
    // a comparison that respected case would report no pack for all 13 German
    // cases while both sides held the same country.
    const { packs } = resolveMarketPacks(INSTALLED, null, 'DE');
    expect(packs.map((p) => p.slug)).toEqual(['bimhessen-de']);
  });

  it('tells an applied pack apart from the same pack switched off', () => {
    // This is the assertion the feature exists for, and it is written as a
    // comparison of the two results rather than as two separate checks: on
    // this deployment nothing is applied, so a resolver that never consulted
    // active_slug would return the identical value in both calls and a pair of
    // one-sided assertions would both pass on it.
    const off = resolveMarketPacks(INSTALLED, null, 'GB');
    const on = resolveMarketPacks(INSTALLED, 'uk-jct', 'GB');

    expect(off.applied).toBeNull();
    expect(on.applied?.slug).toBe('uk-jct');
    expect(on.applied).not.toEqual(off.applied);
    // The list of candidates is the same either way; only the verdict moves.
    expect(on.packs.map((p) => p.slug)).toEqual(off.packs.map((p) => p.slug));
  });

  it('puts the applied pack first among the several that serve one market', () => {
    const { packs, applied } = resolveMarketPacks(INSTALLED, 'us-texas', 'US');
    expect(applied?.slug).toBe('us-texas');
    expect(packs.map((p) => p.slug)).toEqual(['us-texas', 'us-california', 'us-costdata']);
  });

  it('reports no pack for a market that has none rather than the nearest one', () => {
    // Ten shipped cases carry ES and no Spanish pack exists. Silence is the
    // true answer there, and a resolver that fell back to something plausible
    // would put a German pack under a Spanish case.
    expect(resolveMarketPacks(INSTALLED, null, 'ES')).toEqual({ packs: [], applied: null });
  });

  it('never lets a cross-region pack stand in for a market', () => {
    // XX is a pack's own word for "no single market". Treated as a country it
    // would match itself, and every case whose region was somehow XX would be
    // told that modular-prefab covers its standards.
    expect(resolveMarketPacks(INSTALLED, null, 'XX').packs).toEqual([]);
    expect(resolveMarketPacks(INSTALLED, null, 'all').packs).toEqual([]);
    expect(resolveMarketPacks(INSTALLED, null, undefined).packs).toEqual([]);
  });
});

describe('packCountryCode', () => {
  it('reports XX as itself rather than as no country', () => {
    // Callers matching a market have to exclude it, and they can only do that
    // if it reaches them. Collapsing it to null here would hide the choice.
    expect(packCountryCode(pack('modular-prefab', 'XX'))).toBe('xx');
  });

  it('falls back to the region subtag of the locale when metadata is silent', () => {
    expect(packCountryCode(pack('x', null, 'fr-CA'))).toBe('ca');
    expect(packCountryCode(pack('x', null, 'en'))).toBeNull();
  });
});

describe('packSummary', () => {
  it('keeps the clause before the colon when it reads as a summary', () => {
    expect(packSummary('Pre-configured for UK general contractors: RICS NRM 1+2, JCT')).toBe(
      'Pre-configured for UK general contractors',
    );
  });

  it('keeps the whole text when the head is no shorter than it', () => {
    // A description with no colon has no head to take, and returning an empty
    // string would drop the only sentence the card has.
    expect(packSummary('Formwork and falsework engineering')).toBe(
      'Formwork and falsework engineering',
    );
  });

  it('keeps the whole text rather than a head too long to be a summary', () => {
    const long = `${'a'.repeat(120)}: tail`;
    expect(packSummary(long)).toBe(long);
  });

  it('returns an empty string for a pack with no description', () => {
    expect(packSummary(null)).toBe('');
    expect(packSummary(undefined)).toBe('');
    expect(packSummary('   ')).toBe('');
  });
});

describe('packOutsideMarkets', () => {
  const sa = { markets: ['SA'], all_markets: false };

  it('flags a pack from another market', () => {
    expect(packOutsideMarkets('us', sa)).toBe(true);
    expect(packOutsideMarkets('sa', sa)).toBe(false);
  });

  it('never flags a cross-region pack, an unknown country or an unscoped workspace', () => {
    expect(packOutsideMarkets('xx', sa)).toBe(false);
    expect(packOutsideMarkets(null, sa)).toBe(false);
    expect(packOutsideMarkets('us', undefined)).toBe(false);
    expect(packOutsideMarkets('us', { markets: [], all_markets: false })).toBe(false);
    expect(packOutsideMarkets('us', { markets: ['SA'], all_markets: true })).toBe(false);
  });
});
