// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The browser's region decides the defaults a first run is offered: the country
// preset and cost database in the setup wizard, and the market the dashboard's
// cases card leads with. Keyed on the UI language alone, every English reader
// was offered the United States base and the first English preset, and an
// en-CA dashboard, whose plain `en` names no country, opened its cases on the
// largest market, Germany, with the rest of the shelf (Russia among it) beside.
//
// Everything here reads shipped data (the curated presets, the cost database
// catalogue, the case catalogue), so a market that gains or loses data moves
// the answers without an edit here.
//
// Run:  npx vitest run src/features/onboarding/__tests__/browserRegionDefaults.test.ts
import { afterEach, describe, expect, it } from 'vitest';

import {
  browserRegionForLanguage,
  detectBrowserRegion,
  detectCountry,
  detectCountryForLanguage,
} from '@/app/i18n';
import { countCasesByMarket, resolveHomeMarket } from '@/features/cases/marketCases';
import { PLAYBOOKS } from '@/features/cases/playbooks';

import { resolveCountryOffer } from '../countryOffer';
import { suggestDataSetup } from '../OnboardingWizard';

const REAL_LANGUAGE = navigator.language;
const REAL_LANGUAGES = navigator.languages;

function browser(language: string, languages: string[] = [language]): void {
  Object.defineProperty(window.navigator, 'language', { value: language, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: languages, configurable: true });
}

afterEach(() => {
  Object.defineProperty(window.navigator, 'language', { value: REAL_LANGUAGE, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: REAL_LANGUAGES, configurable: true });
});

/** The UI language a first run opens in for these browsers (what
 *  `resolveInitialLanguage` answers; pinned by firstRunLanguageKeepsTheRegion). */
const UI_LANGUAGE: Record<string, string> = {
  'en-CA': 'en',
  'fr-CA': 'fr',
  'en-US': 'en-US',
  'de-DE': 'de',
  'de-AT': 'de',
  'pt-BR': 'pt-BR',
  'en-NZ': 'en',
  'is-IS': 'en',
};

const MARKETS = [...countCasesByMarket(PLAYBOOKS).keys()].sort();

describe('the country a browser names', () => {
  it.each([
    ['en-CA', 'ca'],
    ['fr-CA', 'ca'],
    ['en-US', 'us'],
    ['de-DE', 'de'],
    ['de-AT', 'at'],
    ['pt-BR', 'br'],
    ['en-NZ', 'nz'],
    ['is-IS', 'is'],
  ])('%s names %s', (tag, country) => {
    browser(tag);
    expect(detectBrowserRegion()).toBe(country);
    expect(detectCountry()).toBe(country);
  });

  it('reads the region from a later entry in the same language', () => {
    browser('de', ['de', 'de-AT', 'en-US']);
    expect(detectBrowserRegion()).toBe('at');
  });

  it('does not borrow a region from another language further down the list', () => {
    browser('de', ['de', 'en-US']);
    expect(detectBrowserRegion()).toBeNull();
    expect(detectCountry('de')).toBe('de');
  });

  it("stops going by the browser once the reader picks another language", () => {
    browser('en-US');
    // en-US is the factory default of many machines far from the US, so a
    // reader who switches the app to German is read by their choice.
    expect(detectCountryForLanguage('de')).toBe('de');
    expect(browserRegionForLanguage('de')).toBeNull();
    browser('fr-CA');
    expect(detectCountryForLanguage('fr')).toBe('ca');
    expect(browserRegionForLanguage('fr')).toBe('ca');
  });
});

describe('the setup wizard defaults', () => {
  function wizardFor(tag: string) {
    browser(tag);
    const ui = UI_LANGUAGE[tag]!;
    const country = detectCountryForLanguage(ui);
    return { offer: resolveCountryOffer(detectCountry(), []), data: suggestDataSetup(country, ui) };
  }

  it('offers Canada, its preset and the Toronto base, to an en-CA browser', () => {
    const { offer, data } = wizardFor('en-CA');
    expect(offer?.kind === 'preset' && offer.preset.id).toBe('ca');
    expect(data).toEqual({ region: 'ENG_TORONTO', packId: 'ca' });
  });

  it('offers Canada to a fr-CA browser too', () => {
    const { offer, data } = wizardFor('fr-CA');
    expect(offer?.kind === 'preset' && offer.preset.id).toBe('ca');
    expect(data).toEqual({ region: 'ENG_TORONTO', packId: 'ca' });
  });

  it('offers the United States to en-US', () => {
    expect(wizardFor('en-US').data).toEqual({ region: 'USA_USD', packId: 'us' });
  });

  it('offers Germany to de-DE', () => {
    expect(wizardFor('de-DE').data).toEqual({ region: 'DE_BERLIN', packId: 'de' });
  });

  it('offers Brazil to pt-BR', () => {
    const { data } = wizardFor('pt-BR');
    expect(data.packId).toBe('br');
  });

  it('offers New Zealand its own preset and base', () => {
    expect(wizardFor('en-NZ').data).toEqual({ region: 'NZ_AUCKLAND', packId: 'nz' });
  });

  it('offers de-AT no Austrian preset, because there is none, and falls back to the language', () => {
    const { offer, data } = wizardFor('de-AT');
    expect(offer).toBeNull();
    // Austria has no preset and no base of its own; the German-language
    // suggestion is what a German reader was offered before.
    expect(data).toEqual({ region: 'DE_BERLIN', packId: 'de' });
  });

  it('gives a region with no data of its own the language suggestion and no country offer', () => {
    const { offer, data } = wizardFor('is-IS');
    expect(offer).toBeNull();
    expect(data).toEqual(suggestDataSetup(null, 'en'));
  });

  it('files Britain under its preset id, not its ISO code', () => {
    expect(suggestDataSetup('gb', 'en').packId).toBe('uk');
    expect(suggestDataSetup('gb', 'en').region).toBe('UK_GBP');
  });
});

describe("the dashboard's home market", () => {
  function homeMarketFor(tag: string) {
    browser(tag);
    const ui = UI_LANGUAGE[tag]!;
    return resolveHomeMarket({ language: ui, browserRegion: browserRegionForLanguage(ui), markets: MARKETS });
  }

  it('leads an en-CA dashboard with Canada, not with the largest market', () => {
    expect(MARKETS).toContain('CA');
    expect(homeMarketFor('en-CA')).toEqual({ market: 'CA', source: 'region' });
  });

  it('leads a fr-CA dashboard with Canada', () => {
    expect(homeMarketFor('fr-CA')).toEqual({ market: 'CA', source: 'region' });
  });

  it('leads en-US with the United States and de-DE with Germany', () => {
    expect(homeMarketFor('en-US').market).toBe('US');
    expect(homeMarketFor('de-DE').market).toBe('DE');
  });

  it('leads pt-BR with Brazil', () => {
    expect(homeMarketFor('pt-BR').market).toBe('BR');
  });

  it('falls back to the language for a region with no cases', () => {
    // Austria has no cases: the German-language market answers, labelled as
    // the language's, never as the reader's region.
    expect(MARKETS).not.toContain('AT');
    expect(homeMarketFor('de-AT')).toEqual({ market: 'DE', source: 'language' });
  });

  it('claims no market for a region and language that reach none', () => {
    expect(MARKETS).not.toContain('IS');
    expect(homeMarketFor('is-IS')).toEqual({ market: null, source: null });
  });

  it('lets an applied pack outrank the browser region', () => {
    browser('en-CA');
    expect(
      resolveHomeMarket({ language: 'en', packCountry: 'us', browserRegion: 'ca', markets: MARKETS }),
    ).toEqual({ market: 'US', source: 'pack' });
  });
});
