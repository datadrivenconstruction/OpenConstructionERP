// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The ready-made pack grid preselects the reader's own country's pack and
// nothing else. It fell back to the first pack by slug, so an en-CA first run
// (no Canadian pack ships with the community wheel) opened with Australia
// selected and a "Set up Australia" button under the Canada offer, and an
// en-US one opened on California, the first of three US packs.
//
// Run:  npx vitest run src/features/onboarding/__tests__/readyPackPreselect.test.tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const { fetchInstalledPacks } = vi.hoisted(() => ({ fetchInstalledPacks: vi.fn() }));

vi.mock('../partnerPacksApi', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, fetchInstalledPacks };
});

import { packToPreselect } from '../countryOffer';
import { ReadyPackPicker } from '../OnboardingWizard';

function pack(slug: string, country: string, partnerName: string) {
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
    branding: {},
    has_onboarding_script: false,
    metadata: { country },
  };
}

/** A slice of what the community wheel ships, in the slug order the server
 *  lists it: Australia first, no Canadian pack, three packs for the US. */
const WHEEL = [
  pack('aus', 'AU', 'Australia Construction Pack'),
  pack('brazil-sinapi', 'BR', 'Brazil Construction Pack'),
  pack('germany-de', 'DE', 'Germany Construction Pack'),
  pack('modular-prefab', 'XX', 'Modular & Prefab Pack'),
  pack('us-california', 'US', 'California Construction Pack'),
  pack('us-costdata', 'US', 'US Construction Pack'),
  pack('us-texas', 'US', 'Texas Construction Pack'),
];

const REAL_LANGUAGE = navigator.language;
const REAL_LANGUAGES = navigator.languages;

function browser(language: string): void {
  Object.defineProperty(window.navigator, 'language', { value: language, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: [language], configurable: true });
}

afterEach(() => {
  Object.defineProperty(window.navigator, 'language', { value: REAL_LANGUAGE, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: REAL_LANGUAGES, configurable: true });
});

async function renderPicker() {
  fetchInstalledPacks.mockResolvedValue({ installed: WHEEL });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ReadyPackPicker
          onActivateLocale={() => undefined}
          onInstalled={() => undefined}
          onFallback={() => undefined}
          onBack={() => undefined}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  // The grid is drawn once the packs arrive.
  await screen.findAllByRole('button', { pressed: false });
}

function pressedTiles(): HTMLElement[] {
  return screen.queryAllByRole('button', { pressed: true });
}

describe('which pack the ready-made grid preselects', () => {
  it('preselects no other country for an en-CA reader', async () => {
    browser('en-CA');
    await renderPicker();
    expect(pressedTiles()).toEqual([]);
    expect(document.body.textContent).not.toMatch(/Set up Australia/);
  });

  it('preselects the one pack of the reader\'s own country', async () => {
    browser('pt-BR');
    await renderPicker();
    const pressed = pressedTiles();
    expect(pressed).toHaveLength(1);
    expect(pressed[0]?.textContent).toMatch(/Brazil/);
  });

  it('leaves the choice to an en-US reader whose country has several packs', async () => {
    browser('en-US');
    await renderPicker();
    expect(pressedTiles()).toEqual([]);
  });
});

describe('packToPreselect', () => {
  it.each([
    ['ca', null],
    ['br', 'brazil-sinapi'],
    ['de', 'germany-de'],
    ['us', null],
    ['xx', null],
    [null, null],
  ])('%s -> %s', (country, slug) => {
    expect(packToPreselect(country, WHEEL)).toBe(slug);
  });
});
