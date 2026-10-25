// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The ready-made pack step as a catalogue: a search box, type chips with
// counts, country packs grouped by market band (the reader's own market
// first), the other pack types under their own headings, and the company
// types as a second, optional choice that is written together with the pack.
//
// Run:  npx vitest run src/features/onboarding/__tests__/readyPackBrowse.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const { fetchInstalledPacks, fullInstallPackStream } = vi.hoisted(() => ({
  fetchInstalledPacks: vi.fn(),
  fullInstallPackStream: vi.fn(),
}));
vi.mock('../partnerPacksApi', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, fetchInstalledPacks, fullInstallPackStream };
});

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual('@/shared/lib/api');
  return { ...actual, ...api };
});

import { ReadyPackPicker } from '../OnboardingWizard';
import { useBackgroundInstallStore } from '@/stores/useBackgroundInstallStore';

function pack(slug, country, name, type = 'country', extra = {}) {
  return {
    slug,
    type,
    partner_name: name,
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
    ...extra,
  };
}

/** Listed the way the server lists them, by slug: Canada sorts before Belgium. */
const WHEEL = [
  pack('batimatech-ca', 'CA', 'Canada Batimatech', 'partner'),
  pack('belgium-be', 'BE', 'Belgium Construction Pack', 'country', { default_currency: 'EUR' }),
  pack('doka-formwork', 'XX', 'Doka Formwork Pack', 'industry'),
  pack('germany-de', 'DE', 'Germany Construction Pack', 'country', {
    default_locale: 'de',
    default_currency: 'EUR',
    validation_rule_sets: ['din276'],
  }),
  pack('austria-at', 'AT', 'Austria Construction Pack', 'country', { default_currency: 'EUR' }),
  pack('brazil-sinapi', 'BR', 'Brazil Construction Pack', 'country', { default_locale: 'pt', default_currency: 'BRL' }),
  pack('retail-showcase', 'XX', 'Discount Retail Showcase', 'showcase'),
];

const PRESETS = [
  { key: 'general_contractor', label: 'General Contractor', description: 'Builds it all.', icon: 'Building2', tags: [], enabled_modules: ['boq'], module_count: 1 },
  { key: 'estimator', label: 'Estimator', description: 'Prices work.', icon: 'Calculator', tags: ['cost'], enabled_modules: ['boq', 'costs'], module_count: 2 },
];

const REAL_LANGUAGE = navigator.language;
const REAL_LANGUAGES = navigator.languages;
function browser(language) {
  Object.defineProperty(window.navigator, 'language', { value: language, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: [language], configurable: true });
}

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  fullInstallPackStream.mockReset();
  useBackgroundInstallStore.getState().dismiss();
  fetchInstalledPacks.mockResolvedValue({ installed: WHEEL });
  api.apiGet.mockImplementation((path) => {
    if (path === '/v1/users/onboarding-presets/') return Promise.resolve(PRESETS);
    if (path === '/v1/users/onboarding-presets/core/') return Promise.resolve({ core_modules: [] });
    if (path === '/v1/users/me/onboarding/') return Promise.resolve({ completed: false, company_type: null });
    if (path === '/v1/users/me/module-preferences/') return Promise.resolve({ modules: {} });
    return Promise.reject(new Error(`no fake for GET ${path}`));
  });
  api.apiPost.mockImplementation((path, body) =>
    Promise.resolve(path === '/v1/users/me/onboarding/' ? { completed: true, company_type: body.company_type } : {}),
  );
});

afterEach(() => {
  cleanup();
  Object.defineProperty(window.navigator, 'language', { value: REAL_LANGUAGE, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: REAL_LANGUAGES, configurable: true });
});

async function renderPicker(props = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const handlers = {
    onActivateLocale: vi.fn(),
    onInstalled: vi.fn(),
    onFallback: vi.fn(),
    onBack: vi.fn(),
    onInstallStarted: vi.fn(),
    onCompanyApplied: vi.fn(),
    ...props,
  };
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ReadyPackPicker {...handlers} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  if (props.installingSlug) {
    await screen.findByTestId('ready-pack-confirm');
    return handlers;
  }
  await screen.findByTestId('ready-pack-browser');
  // The company types arrive with their own request.
  await screen.findByTestId('ready-pack-company-general_contractor');
  return handlers;
}

const tileNames = (container) =>
  within(container)
    .getAllByTestId(/^ready-pack-tile-/)
    .map((el) => el.getAttribute('title'));

describe('the pack step as a catalogue', () => {
  it('groups country packs by market band and keeps every other type under its own heading', async () => {
    browser('en-US');
    await renderPicker();

    const europe = screen.getByTestId('ready-pack-group-europe');
    const americas = screen.getByTestId('ready-pack-group-americas');
    // Sorted by the displayed name inside a group, not by slug.
    expect(tileNames(europe)).toEqual([
      'Austria Construction Pack',
      'Belgium Construction Pack',
      'Germany Construction Pack',
    ]);
    // The Canadian partner pack is not a country between Brazil and nothing.
    expect(tileNames(americas)).toEqual(['Brazil Construction Pack']);
    expect(tileNames(screen.getByTestId('ready-pack-group-partner'))).toEqual(['Canada Batimatech']);
    expect(tileNames(screen.getByTestId('ready-pack-group-industry'))).toEqual(['Doka Formwork Pack']);
    expect(tileNames(screen.getByTestId('ready-pack-group-showcase'))).toEqual(['Discount Retail Showcase']);
    // No industry pack sits among the countries.
    expect(within(europe).queryByTestId('ready-pack-tile-doka-formwork')).toBeNull();
  });

  it('leads with the reader\'s own market under the suggested heading', async () => {
    browser('de-DE');
    await renderPicker();
    const groups = screen.getAllByTestId(/^ready-pack-group-/).map((el) => el.getAttribute('data-testid'));
    expect(groups[0]).toBe('ready-pack-group-home');
    expect(tileNames(screen.getByTestId('ready-pack-group-home'))).toEqual(['Germany Construction Pack']);
    expect(screen.getByRole('heading', { name: 'Suggested for your region' })).toBeTruthy();
  });

  it('searches the name, the country, the currency, the language and the standard', async () => {
    browser('en-US');
    await renderPicker();
    const search = screen.getByTestId('ready-pack-search');
    const shown = () => screen.queryAllByTestId(/^ready-pack-tile-/).map((el) => el.getAttribute('title'));

    fireEvent.change(search, { target: { value: 'brazil' } });
    expect(shown()).toEqual(['Brazil Construction Pack']);
    fireEvent.change(search, { target: { value: 'BRL' } });
    expect(shown()).toEqual(['Brazil Construction Pack']);
    fireEvent.change(search, { target: { value: 'portuguese' } });
    expect(shown()).toEqual(['Brazil Construction Pack']);
    fireEvent.change(search, { target: { value: 'din 276' } });
    expect(shown()).toEqual(['Germany Construction Pack']);
    // A country in the reader's own language, accents folded.
    fireEvent.change(search, { target: { value: 'austria' } });
    expect(shown()).toEqual(['Austria Construction Pack']);

    fireEvent.change(search, { target: { value: 'zzzz' } });
    expect(shown()).toEqual([]);
    expect(screen.getByTestId('ready-pack-empty')).toBeTruthy();
  });

  it('counts and filters by type with the same chips as the catalogue', async () => {
    browser('en-US');
    await renderPicker();
    const chip = (key) => screen.getByTestId(`ready-pack-type-${key}`);

    expect(within(chip('all')).getByText('9')).toBeTruthy(); // 7 packs + 2 company types
    expect(within(chip('country')).getByText('4')).toBeTruthy();
    expect(within(chip('industry')).getByText('1')).toBeTruthy();
    expect(within(chip('company')).getByText('2')).toBeTruthy();

    fireEvent.click(chip('industry'));
    expect(chip('industry').getAttribute('aria-checked')).toBe('true');
    expect(screen.queryAllByTestId(/^ready-pack-tile-/).map((el) => el.getAttribute('title'))).toEqual([
      'Doka Formwork Pack',
    ]);
    expect(screen.queryByTestId('ready-pack-company-types')).toBeNull();

    fireEvent.click(chip('company'));
    expect(screen.queryAllByTestId(/^ready-pack-tile-/)).toEqual([]);
    expect(within(screen.getByTestId('ready-pack-company-types')).getAllByRole('button')).toHaveLength(2);

    // The search narrows the company types too.
    fireEvent.change(screen.getByTestId('ready-pack-search'), { target: { value: 'prices' } });
    expect(within(screen.getByTestId('ready-pack-company-types')).getAllByRole('button')).toHaveLength(1);
  });

  it('clips a long name instead of letting it overflow the tile', async () => {
    browser('en-US');
    await renderPicker();
    const tile = screen.getByTestId('ready-pack-tile-batimatech-ca');
    const name = within(tile).getByText('Canada Batimatech');
    expect(name.className).toMatch(/line-clamp-2/);
    expect(name.getAttribute('title')).toBe('Canada Batimatech');
    expect(tile.className).toMatch(/min-w-0/);
  });
});

describe('a company type beside the pack', () => {
  it('sets up the pack and writes the company type for the reader', async () => {
    browser('en-US');
    fullInstallPackStream.mockImplementation(async (_slug, onEvent) => {
      onEvent({ type: 'step_done', step: 'locale', status: 'ok', detail: { locale: 'de' } });
    });
    const handlers = await renderPicker();

    fireEvent.click(screen.getByTestId('ready-pack-tile-germany-de'));
    // The company type is optional: the plain button reads as before.
    expect(screen.getByTestId('ready-pack-install').textContent).toBe('Set up Germany Construction Pack');
    fireEvent.click(screen.getByTestId('ready-pack-company-estimator'));
    expect(screen.getByTestId('ready-pack-company-estimator').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByTestId('ready-pack-install').textContent).toBe(
      'Set up Germany Construction Pack and Estimator',
    );

    fireEvent.click(screen.getByTestId('ready-pack-install'));

    await waitFor(() => expect(handlers.onInstalled).toHaveBeenCalledWith('germany-de'));
    expect(handlers.onInstallStarted).toHaveBeenCalledWith('germany-de');
    expect(fullInstallPackStream).toHaveBeenCalledTimes(1);
    expect(fullInstallPackStream.mock.calls[0][0]).toBe('germany-de');
    const writes = api.apiPost.mock.calls.filter(([p]) => p === '/v1/users/me/onboarding/');
    expect(writes).toHaveLength(1);
    expect(writes[0][1]).toMatchObject({ company_type: 'estimator', enabled_modules: ['boq', 'costs'] });
    expect(handlers.onCompanyApplied).toHaveBeenCalledWith(expect.objectContaining({ key: 'estimator' }));
    // The company type is written before the reader is told the pack is ready.
    expect(api.apiPost.mock.invocationCallOrder[0]).toBeLessThan(handlers.onInstalled.mock.invocationCallOrder[0]);
  });

  it('writes no profile when none was chosen', async () => {
    browser('en-US');
    fullInstallPackStream.mockImplementation(async (_slug, onEvent) => {
      onEvent({ type: 'step_done', step: 'locale', status: 'ok', detail: { locale: 'en' } });
    });
    const handlers = await renderPicker();
    fireEvent.click(screen.getByTestId('ready-pack-tile-brazil-sinapi'));
    fireEvent.click(screen.getByTestId('ready-pack-install'));
    await waitFor(() => expect(handlers.onInstalled).toHaveBeenCalledWith('brazil-sinapi'));
    expect(api.apiPost.mock.calls.filter(([p]) => p === '/v1/users/me/onboarding/')).toHaveLength(0);
    expect(handlers.onCompanyApplied).not.toHaveBeenCalled();
  });

  it('asks for a pack when only a company type is chosen, and lets it be cleared', async () => {
    browser('en-US');
    await renderPicker();
    fireEvent.click(screen.getByTestId('ready-pack-company-estimator'));
    expect(screen.getByTestId('ready-pack-company-needs-pack')).toBeTruthy();
    expect(screen.queryByTestId('ready-pack-install')).toBeNull();
    // Choosing the same tile again clears it.
    fireEvent.click(screen.getByTestId('ready-pack-company-estimator'));
    expect(screen.queryByTestId('ready-pack-company-needs-pack')).toBeNull();
  });
});

describe('while an install runs', () => {
  it('offers appearance and finish instead of the grid, and cannot start a second install', async () => {
    browser('en-US');
    const onAdjustAppearance = vi.fn();
    const onFinish = vi.fn();
    await renderPicker({
      installingSlug: 'germany-de',
      installedSlug: null,
      onAdjustAppearance,
      onFinish,
    });
    expect(screen.queryByTestId('ready-pack-browser')).toBeNull();
    expect(screen.queryByTestId('ready-pack-install')).toBeNull();
    // Finish waits for the language; the look can be adjusted at once.
    expect(screen.getByTestId('ready-pack-finish').disabled).toBe(true);
    fireEvent.click(screen.getByTestId('ready-pack-adjust-look'));
    expect(onAdjustAppearance).toHaveBeenCalledTimes(1);
  });
});
