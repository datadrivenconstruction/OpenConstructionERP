// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - the language-to-market default.
//
// Written against the REAL language registry and the REAL catalogue, not a
// fixture, because the claim being made is about them: that `es-MX` is never
// led with Spanish cases naming Spanish law. A fixture would let that claim
// stay true about the fixture while the shipped registry says something else.
//
// The assertions below are properties rather than an inventory of which
// languages currently reach a market. Italy gaining its first case would break
// an inventory and would not break a property, and the property is what has to
// hold. Mexico and Brazil are the worked demonstration: both gained a case
// after this suite was written, `es-MX` and `pt-BR` began reaching them with
// no edit here or in the module under test, and nothing below had to change.

import { describe, expect, it } from 'vitest';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { PLAYBOOKS } from './playbooks';
import { buildCaseNumbers } from './stages';
import { homeMarketFirst, homeMarketForLanguage } from './homeMarket';

/** The markets the catalogue actually carries, read the way the hub reads
 *  them, so this suite tracks the shipped data rather than a copy of it. */
const MARKETS = [
  ...new Set(PLAYBOOKS.map((p) => p.region).filter((r): r is string => Boolean(r))),
].sort();

describe('homeMarketForLanguage', () => {
  it('the catalogue carries market-specific cases at all', () => {
    // Everything below is vacuous if it does not.
    expect(MARKETS.length).toBeGreaterThan(0);
  });

  it('answers with the country the language registry itself declares', () => {
    // The rule, stated over every shipped language at once: a language reaches
    // the country it already declares for its flag, and only when the
    // catalogue has cases for it. Nothing is derived from the language code,
    // which is what keeps `uk` (Ukrainian) away from the `uk` this codebase
    // uses elsewhere to mean Britain.
    for (const lang of SUPPORTED_LANGUAGES) {
      const declared = lang.country.toUpperCase();
      const expected = MARKETS.includes(declared) ? declared : null;
      expect(
        homeMarketForLanguage(lang.code, MARKETS),
        `${lang.code} declares ${declared}`,
      ).toBe(expected);
    }
  });

  it('never answers with a market the catalogue has no cases for', () => {
    for (const lang of SUPPORTED_LANGUAGES) {
      const market = homeMarketForLanguage(lang.code, MARKETS);
      if (market !== null) expect(MARKETS).toContain(market);
    }
  });

  it('keeps the Ukrainian language away from the British market', () => {
    // `uk` is Ukrainian as a language and Britain as a region in this
    // codebase's other vocabularies (BoQ presets, country packs). A mapping
    // that read the language code as a region would send every Ukrainian
    // reader to the British cases, and would look entirely reasonable doing
    // it.
    expect(homeMarketForLanguage('uk', MARKETS)).not.toBe('GB');
    expect(homeMarketForLanguage('uk', [...MARKETS, 'UK'])).not.toBe('UK');
  });

  it('separates the two English entries', () => {
    expect(homeMarketForLanguage('en', MARKETS)).toBe('GB');
    expect(homeMarketForLanguage('en-US', MARKETS)).toBe('US');
  });

  it('does not hand a Spanish-speaking market the cases written for Spain', () => {
    // The sharp one. Spain's cases implement Spanish public procurement,
    // FIEBDC-3 and Spanish site paperwork. Leading with them for a Mexican,
    // Chilean or Colombian reader would name a law that does not apply where
    // they work, which is worse than showing them nothing in particular.
    expect(homeMarketForLanguage('es', MARKETS)).toBe('ES');
    for (const code of ['es-MX', 'es-CL', 'es-CO']) {
      expect(homeMarketForLanguage(code, MARKETS), code).not.toBe('ES');
    }
  });

  it('does not hand Brazil the cases written for Portugal, or the reverse', () => {
    const pt = homeMarketForLanguage('pt', MARKETS);
    const ptBR = homeMarketForLanguage('pt-BR', MARKETS);
    // Equal only when both are null, which was the answer while neither market
    // had cases. Brazil has one now and Portugal does not, so today they have
    // already parted company, and they must stay parted if Portugal gains one.
    if (pt !== null || ptBR !== null) expect(pt).not.toBe(ptBR);
  });

  it('reads an unregistered tag through its region subtag, never its language', () => {
    // A tag the registry does not list is answered by where the reader says
    // they are, and the subtag wins outright: Austria and Switzerland are not
    // served the German cases as if their law were the same, and French
    // Canada reaches the Canadian ones even though French itself does not.
    expect(homeMarketForLanguage('de-AT', MARKETS)).toBeNull();
    expect(homeMarketForLanguage('de-CH', MARKETS)).toBeNull();
    expect(homeMarketForLanguage('fr-CA', MARKETS)).toBe(
      MARKETS.includes('CA') ? 'CA' : null,
    );
    // Lower case and mixed case are the same tag; i18next is not the only
    // thing that can put a language code in front of this.
    expect(homeMarketForLanguage('EN-us', MARKETS)).toBe('US');
  });

  it('answers nothing for a tag it cannot place, and for an empty catalogue', () => {
    for (const code of ['', ' ', 'xx', 'zz-ZZ', null, undefined]) {
      expect(homeMarketForLanguage(code, MARKETS), String(code)).toBeNull();
    }
    for (const lang of SUPPORTED_LANGUAGES) {
      expect(homeMarketForLanguage(lang.code, []), lang.code).toBeNull();
    }
  });
});

describe('homeMarketFirst', () => {
  const numbers = buildCaseNumbers(PLAYBOOKS);
  const positionOf = (pb: { id: string }) => numbers.get(pb.id) ?? 0;
  const catalogueOrder = [...PLAYBOOKS].sort((a, b) => positionOf(a) - positionOf(b));

  it('returns the catalogue untouched when the language names no market', () => {
    const ordered = homeMarketFirst(PLAYBOOKS, null, positionOf);
    expect(ordered.map((pb) => pb.id)).toEqual(catalogueOrder.map((pb) => pb.id));
  });

  it('loses no case and repeats none, for any market', () => {
    // The whole design rests on this: it orders, it does not filter. A reader
    // whose language names a market still has the entire library in front of
    // them, 140 universal cases included.
    for (const market of MARKETS) {
      const ordered = homeMarketFirst(PLAYBOOKS, market, positionOf);
      expect(ordered).toHaveLength(PLAYBOOKS.length);
      expect(new Set(ordered.map((pb) => pb.id)).size).toBe(PLAYBOOKS.length);
    }
  });

  it('puts every case for the market in front of every case that is not', () => {
    for (const market of MARKETS) {
      const ordered = homeMarketFirst(PLAYBOOKS, market, positionOf);
      const count = PLAYBOOKS.filter((pb) => pb.region === market).length;
      expect(count, market).toBeGreaterThan(0);
      expect(ordered.slice(0, count).every((pb) => pb.region === market)).toBe(true);
      expect(ordered.slice(count).some((pb) => pb.region === market)).toBe(false);
    }
  });

  it('leaves the order inside each group exactly as the catalogue had it', () => {
    for (const market of MARKETS) {
      const ordered = homeMarketFirst(PLAYBOOKS, market, positionOf);
      const home = ordered.filter((pb) => pb.region === market).map(positionOf);
      const rest = ordered.filter((pb) => pb.region !== market).map(positionOf);
      expect(home, market).toEqual([...home].sort((a, b) => a - b));
      expect(rest, market).toEqual([...rest].sort((a, b) => a - b));
    }
  });

  it('is a no-op for a market with no cases in the list it is given', () => {
    const ordered = homeMarketFirst(PLAYBOOKS, 'ZZ', positionOf);
    expect(ordered.map((pb) => pb.id)).toEqual(catalogueOrder.map((pb) => pb.id));
  });
});
