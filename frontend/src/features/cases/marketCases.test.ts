// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - the dashboard's market resolution and shelf order.
//
// Written against the REAL language registry and the REAL catalogue for the
// same reason `homeMarket.test.ts` is: the claims are about what a shipped
// reader is shown. Where a claim depends on a market having cases (Brazil,
// Mexico, Hungary each carry exactly one at the time of writing) the test
// says so and derives the expectation from the catalogue rather than
// hard-coding a market that a data change could empty.
//
// Run: npx vitest run src/features/cases/marketCases.test.ts

import { describe, expect, it } from 'vitest';

import { homeMarketForLanguage } from './homeMarket';
import {
  casesForMarket,
  countCasesByMarket,
  nearestMarketsForLanguage,
  orderMarkets,
  resolveHomeMarket,
} from './marketCases';
import { PLAYBOOKS } from './playbooks';
import { buildCaseNumbers } from './stages';

/** The markets the catalogue actually carries, read the way the card reads
 *  them, so the suite tracks shipped data rather than a copy of it. */
const COUNTS = countCasesByMarket(PLAYBOOKS);
const MARKETS = [...COUNTS.keys()].sort();

const resolve = (language: string, packCountry: string | null = null) =>
  resolveHomeMarket({ language, packCountry, markets: MARKETS });

describe('resolveHomeMarket, the language table', () => {
  it('the catalogue carries the markets the table below relies on', () => {
    // Everything after this is vacuous without them.
    for (const market of ['DE', 'ES', 'MX', 'BR', 'CN', 'IN', 'RU', 'SA', 'HU', 'CA', 'GB', 'US']) {
      expect(MARKETS, market).toContain(market);
    }
  });

  it('answers the country a language declares, through the shared helper', () => {
    // The language step is `homeMarketForLanguage` itself, not a second table:
    // whatever the catalogue leads with for a language, this leads with too.
    for (const [language, market] of [
      ['de', 'DE'],
      ['es', 'ES'],
      ['es-MX', 'MX'],
      ['pt-BR', 'BR'],
      ['zh', 'CN'],
      ['hi', 'IN'],
      ['ru', 'RU'],
      ['ar', 'SA'],
      ['en-US', 'US'],
    ] as const) {
      expect(resolve(language), language).toEqual({ market, source: 'language' });
      expect(homeMarketForLanguage(language, MARKETS), language).toBe(market);
    }
  });

  it('keeps es-MX and es-CL apart: Mexico is a market, Spain is only the closest one', () => {
    // The sharp pair. A Mexican reader has cases written for Mexican law and is
    // led with those, as their own market. A Chilean reader has none, is
    // offered the Spanish cases as the nearest in their language, and the
    // source says "nearest" so the card never calls Spain their market.
    expect(resolve('es-MX')).toEqual({ market: 'MX', source: 'language' });
    expect(resolve('es-CL')).toEqual({ market: 'ES', source: 'nearest' });
    expect(resolve('es-CO')).toEqual({ market: 'ES', source: 'nearest' });
    // And Mexico is the next candidate for both, one click away on the shelf.
    expect(nearestMarketsForLanguage('es-CL')).toEqual(['ES', 'MX']);
    expect(nearestMarketsForLanguage('es-CO')).toEqual(['ES', 'MX']);
  });

  it('offers the nearest market to a language whose own country has no cases', () => {
    expect(resolve('pt')).toEqual({ market: 'BR', source: 'nearest' });
    expect(resolve('fr')).toEqual({ market: 'CA', source: 'nearest' });
    expect(resolve('bn')).toEqual({ market: 'IN', source: 'nearest' });
    expect(resolve('hu')).toEqual({ market: 'HU', source: 'nearest' });
    // A regional tag with no row of its own reads through its base language.
    expect(resolve('pt-PT')).toEqual({ market: 'BR', source: 'nearest' });
  });

  it('never offers a nearest market the catalogue has no cases for', () => {
    // The table is a list of candidates, not of answers: strip Brazil out of
    // the catalogue and Portuguese reaches nothing rather than an empty shelf.
    const withoutBrazil = MARKETS.filter((m) => m !== 'BR');
    expect(resolveHomeMarket({ language: 'pt', markets: withoutBrazil })).toEqual({
      market: null,
      source: null,
    });
    // And the second candidate steps in when the first is gone.
    const withoutSpain = MARKETS.filter((m) => m !== 'ES');
    expect(resolveHomeMarket({ language: 'es-CL', markets: withoutSpain })).toEqual({
      market: 'MX',
      source: 'nearest',
    });
  });

  it('English without a pack follows the registry, the same as the catalogue', () => {
    // `en` declares Britain in SUPPORTED_LANGUAGES and `en-US` the United
    // States. The card must lead with what the hub leads with for the same
    // reader, so the answer is read off the shared helper rather than pinned.
    const expected = homeMarketForLanguage('en', MARKETS);
    expect(expected).not.toBeNull();
    expect(resolve('en')).toEqual({ market: expected, source: 'language' });
    // Every other English-speaking market is a candidate behind it.
    for (const market of ['US', 'GB', 'CA', 'AU', 'NZ', 'IN', 'ZA']) {
      expect(nearestMarketsForLanguage('en')).toContain(market);
    }
  });

  it('English with a pack leads with the pack country', () => {
    expect(resolve('en', 'us')).toEqual({ market: 'US', source: 'pack' });
    expect(resolve('en', 'AU')).toEqual({ market: 'AU', source: 'pack' });
    expect(resolve('en', 'ca')).toEqual({ market: 'CA', source: 'pack' });
  });

  it('the pack outranks the language for every language', () => {
    expect(resolve('de', 'us')).toEqual({ market: 'US', source: 'pack' });
    expect(resolve('es-CL', 'mx')).toEqual({ market: 'MX', source: 'pack' });
  });

  it('a pack that names no single market, or a market with no cases, is skipped', () => {
    // `xx` is what a cross-region pack declares; a French pack names a market
    // the catalogue has nothing for. Neither may produce an empty card.
    expect(resolve('de', 'xx')).toEqual({ market: 'DE', source: 'language' });
    expect(resolve('de', 'fr')).toEqual({ market: 'DE', source: 'language' });
    expect(resolve('de', '')).toEqual({ market: 'DE', source: 'language' });
  });

  it('answers nothing for a language that reaches no market', () => {
    for (const language of ['ja', 'tr', 'it', 'xx', '']) {
      expect(resolve(language), language).toEqual({ market: null, source: null });
    }
  });
});

describe('orderMarkets', () => {
  it('puts the home market first and the rest by case count', () => {
    const shelf = orderMarkets(COUNTS, 'ES');
    expect(shelf[0]?.market).toBe('ES');
    const rest = shelf.slice(1).map((e) => e.count);
    expect(rest).toEqual([...rest].sort((a, b) => b - a));
    // Every market exactly once, whatever the order.
    expect(shelf.map((e) => e.market).sort()).toEqual(MARKETS);
  });

  it('orders by count alone when there is no home market', () => {
    const shelf = orderMarkets(COUNTS, null);
    const counts = shelf.map((e) => e.count);
    expect(counts).toEqual([...counts].sort((a, b) => b - a));
    // Ties are broken by code so the shelf never reshuffles between renders.
    for (let i = 1; i < shelf.length; i += 1) {
      const prev = shelf[i - 1]!;
      const next = shelf[i]!;
      if (prev.count === next.count) {
        expect(prev.market.localeCompare(next.market)).toBeLessThan(0);
      }
    }
  });

  it('carries the count the catalogue actually has for each market', () => {
    for (const { market, count } of orderMarkets(COUNTS, 'DE')) {
      expect(count, market).toBe(PLAYBOOKS.filter((pb) => pb.region === market).length);
    }
  });
});

describe('casesForMarket', () => {
  const numbers = buildCaseNumbers(PLAYBOOKS);
  const positionOf = (pb: { id: string }) => numbers.get(pb.id) ?? 0;

  it('returns every case for the market, in catalogue order, and nothing else', () => {
    for (const market of MARKETS) {
      const cases = casesForMarket(PLAYBOOKS, market, positionOf);
      expect(cases.length, market).toBe(COUNTS.get(market));
      expect(cases.every((pb) => pb.region === market), market).toBe(true);
      const positions = cases.map(positionOf);
      expect(positions, market).toEqual([...positions].sort((a, b) => a - b));
    }
  });

  it('is empty for no market', () => {
    expect(casesForMarket(PLAYBOOKS, null, positionOf)).toEqual([]);
    expect(casesForMarket(PLAYBOOKS, 'ZZ', positionOf)).toEqual([]);
  });
});
