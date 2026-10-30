// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The packs page offers markets in the order they matter, not alphabetically.
 *
 * Two halves. The first pins the rules with hand-built packs, so a broken rule
 * says which rule. The second runs every pack manifest actually on disk
 * through those rules, because a band table that is right about invented input
 * and wrong about the shipped forty-three would pass a suite and fail a user.
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import {
  PACK_MARKET_BANDS,
  groupPacksByMarket,
  packMarketBand,
  packMarketRank,
  sortPacksByMarket,
  type PackMarketBand,
  type RegionalPackFacts,
} from '../regionalPack';

/** A pack reduced to what the band rules read. */
function pack(slug: string, country: string | null, locale = 'en', name = slug): RegionalPackFacts {
  return {
    slug,
    partner_name: name,
    default_locale: locale,
    metadata: country === null ? {} : { country },
  };
}

const nameOf = (p: RegionalPackFacts) => p.partner_name;

describe('pack market bands', () => {
  it('orders the bands by market size, with the reader ahead of all of them', () => {
    expect([...PACK_MARKET_BANDS]).toEqual([
      'home',
      'americas',
      'china',
      'india',
      'europe',
      'rest',
      'cross-region',
    ]);
  });

  it('puts the United States ahead of Europe, and China and India between them', () => {
    const us = pack('us-texas', 'US');
    const cn = pack('china-gbt50500', 'CN');
    const inPack = pack('india-cpwd', 'IN');
    const de = pack('germany-de', 'DE');
    const ranks = [us, cn, inPack, de].map((p) => packMarketRank(p, null));
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
    expect(packMarketRank(us, null)).toBeLessThan(packMarketRank(de, null));
  });

  it("puts the reader's own country first, above the largest market", () => {
    const us = pack('us-texas', 'US');
    const pl = pack('poland-pl', 'PL');
    expect(packMarketBand(pl, 'pl')).toBe('home');
    expect(packMarketRank(pl, 'pl')).toBeLessThan(packMarketRank(us, 'pl'));
    // And with no country read from the browser, the size order is untouched.
    expect(packMarketRank(pl, null)).toBeGreaterThan(packMarketRank(us, null));
  });

  it('never treats the cross-region placeholder as a country, in either direction', () => {
    const vertical = pack('modular-prefab', 'XX');
    expect(packMarketBand(vertical, null)).toBe('cross-region');
    // A browser that somehow reported `xx` must not be handed a vertical pack
    // as though it were the reader's own market.
    expect(packMarketBand(vertical, 'xx')).toBe('cross-region');
  });

  it('files a pack that names no country as cross-region rather than guessing', () => {
    // doker-formwork is the live case: an industry pack whose only locale is a
    // bare `de` with no region subtag, so there is nothing to read a country
    // from and inventing Germany would be a claim the pack never made.
    expect(packMarketBand(pack('doker-formwork', null, 'de'), null)).toBe('cross-region');
  });

  it('reads the region subtag when the pack declares no country', () => {
    expect(packMarketBand(pack('nzs', null, 'en-NZ'), null)).toBe('rest');
    expect(packMarketBand(pack('uk-jct', null, 'en-GB'), null)).toBe('europe');
  });

  it('keeps Turkey and Russia out of the European band, because the band is a standards family', () => {
    expect(packMarketBand(pack('turkey-tr', 'TR'), null)).toBe('rest');
    expect(packMarketBand(pack('russia-gesn', 'RU'), null)).toBe('rest');
    expect(packMarketBand(pack('germany-de', 'DE'), null)).toBe('europe');
  });
});

describe('ordering inside a band', () => {
  it('sorts by the name on the card, not by the slug', () => {
    // This is the batimatech-ca case. By slug it lands first in the band; by
    // the name the reader can see it belongs with Canada.
    const packs = [
      pack('batimatech-ca', 'CA', 'fr-CA', 'Canada Pack'),
      pack('canada-ca', 'CA', 'en-CA', 'Canada Construction Pack'),
      pack('us-texas', 'US', 'en-US', 'Texas Construction Pack'),
      pack('brazil-sinapi', 'BR', 'pt-BR', 'Brazil SINAPI Pack'),
    ];
    const ordered = sortPacksByMarket(packs, { nameOf, locale: 'en' }).map((p) => p.slug);
    expect(ordered).toEqual(['brazil-sinapi', 'canada-ca', 'batimatech-ca', 'us-texas']);
  });

  it('collates in the reader language, so the same list reads right in two of them', () => {
    const packs = [pack('z', 'DE', 'de', 'Zurich'), pack('o', 'DE', 'de', 'Örebro')];
    const inGerman = sortPacksByMarket(packs, { nameOf, locale: 'de' }).map((p) => p.slug);
    const inSwedish = sortPacksByMarket(packs, { nameOf, locale: 'sv' }).map((p) => p.slug);
    // German files Ö with O, Swedish files it after Z. A plain `<` cannot be
    // right for both, which is the whole reason a collator is here.
    expect(inGerman).toEqual(['o', 'z']);
    expect(inSwedish).toEqual(['z', 'o']);
  });

  it('returns a new array and leaves the query cache entry alone', () => {
    const packs = [pack('germany-de', 'DE'), pack('us-texas', 'US')];
    const before = packs.map((p) => p.slug);
    const ordered = sortPacksByMarket(packs, { nameOf, locale: 'en' });
    expect(packs.map((p) => p.slug)).toEqual(before);
    expect(ordered).not.toBe(packs);
  });
});

describe('grouping for the headed grid', () => {
  it('drops bands with nothing in them, so no heading stands over an empty row', () => {
    const groups = groupPacksByMarket([pack('germany-de', 'DE'), pack('us-texas', 'US')], {
      nameOf,
      locale: 'en',
    });
    expect(groups.map((g) => g.band)).toEqual(['americas', 'europe']);
  });

  it('keeps every pack, exactly once', () => {
    const packs = [
      pack('us-texas', 'US'),
      pack('china-gbt50500', 'CN'),
      pack('modular-prefab', 'XX'),
      pack('poland-pl', 'PL'),
      pack('japan-jp', 'JP'),
    ];
    const groups = groupPacksByMarket(packs, { nameOf, locale: 'en', homeCountry: 'pl' });
    const flat = groups.flatMap((g) => g.packs.map((p) => p.slug));
    expect(flat.sort()).toEqual(packs.map((p) => p.slug).sort());
    expect(groups[0]?.band).toBe('home');
  });
});

/* ── The shipped packs, not invented ones ──────────────────────────────── */

/** Every pack directory that carries a manifest, with the country it declares. */
function readShippedPacks(): RegionalPackFacts[] {
  const root = join(process.cwd(), '..', 'packs');
  if (!existsSync(root)) return [];
  const out: RegionalPackFacts[] = [];
  for (const slug of readdirSync(root)) {
    const srcDir = join(root, slug, 'src');
    if (!existsSync(srcDir)) continue;
    for (const pkgDir of readdirSync(srcDir)) {
      const manifest = join(srcDir, pkgDir, 'manifest.py');
      if (!existsSync(manifest)) continue;
      const text = readFileSync(manifest, 'utf8');
      const country = /"country":\s*"([^"]*)"/.exec(text)?.[1] ?? null;
      const locale = /default_locale="([^"]*)"/.exec(text)?.[1] ?? 'en';
      const name = /partner_name="([^"]*)"/.exec(text)?.[1] ?? slug;
      out.push({
        slug,
        partner_name: name,
        default_locale: locale,
        metadata: country === null ? {} : { country },
      });
    }
  }
  return out;
}

describe('the packs this repository actually ships', () => {
  const shipped = readShippedPacks();

  it('finds the pack tree, so a silent zero cannot pass as agreement', () => {
    expect(shipped.length, 'no pack manifests found under packs/').toBeGreaterThan(35);
  });

  it('files every one of them into a band', () => {
    const unbanded = shipped.filter((p) => !PACK_MARKET_BANDS.includes(packMarketBand(p, null)));
    expect(unbanded.map((p) => p.slug)).toEqual([]);
  });

  it('leads with the United States and never with a pack sorted by slug', () => {
    const ordered = sortPacksByMarket(shipped, { nameOf, locale: 'en' });
    expect(packMarketBand(ordered[0]!, null)).toBe('americas');
    // The old order was `sorted(by_slug)`, whose first entry is `aus`. If that
    // ever comes back this is the line that says so.
    expect(ordered[0]!.slug).not.toBe('aus');
  });

  it('puts a reader in Hungary in front of the Hungarian pack, not the American one', () => {
    const ordered = sortPacksByMarket(shipped, { nameOf, locale: 'en', homeCountry: 'hu' });
    expect(ordered[0]!.slug).toBe('hungary-hu');
  });

  it('spreads them across the bands instead of dumping them in one', () => {
    const counts = new Map<PackMarketBand, number>();
    for (const p of shipped) {
      const band = packMarketBand(p, null);
      counts.set(band, (counts.get(band) ?? 0) + 1);
    }
    // Every named band has to be non-empty, otherwise the heading for it never
    // renders and the ordering the founder asked for is invisible.
    for (const band of ['americas', 'china', 'india', 'europe', 'rest'] as const) {
      expect(counts.get(band) ?? 0, `band ${band} has no shipped pack`).toBeGreaterThan(0);
    }
    expect(counts.get('europe')!).toBeGreaterThan(counts.get('americas')!);
  });
});
