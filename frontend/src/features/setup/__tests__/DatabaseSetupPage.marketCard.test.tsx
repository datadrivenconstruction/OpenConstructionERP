// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Database Setup used to load a national market card (the Turkish base priced
// into Paris, in French) as its home base, so the plain Turkish base landed and
// the French text never did. The card now goes through the market load, and it
// does not import the home resource catalogue next to it: that catalogue is in
// the home language and currency and would contradict the prices just set.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const { apiGet, apiPost } = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiGet, apiPost };
});

function variant(over = {}) {
  return {
    region: 'TR_NATIONAL',
    variant_id: 'TR_NATIONAL',
    base_region: 'TR_NATIONAL',
    market_catalog: '',
    active: false,
    market: 'Turkiye',
    city: 'National',
    language: 'Turkce',
    lang_code: 'tr',
    text_lang_code: 'tr',
    currency: 'TRY',
    flag: 'tr',
    positions: 22494,
    bundled: true,
    coefficient: false,
    loaded: false,
    loaded_positions: 0,
    ...over,
  };
}

const PARIS = variant({
  variant_id: 'TR_NATIONAL:FR_PARIS_fr',
  market_catalog: 'FR_PARIS_fr',
  market: 'France',
  city: 'Paris',
  language: 'Francais',
  lang_code: 'fr',
  text_lang_code: 'fr',
  currency: 'EUR',
  flag: 'fr',
});

const CATALOG = {
  repo: 'x',
  total_bases: 2,
  total_families: 1,
  loaded_regions: [],
  families: [
    {
      key: 'china',
      name: 'Turkiye (Birim Fiyat)',
      norm_system: 'Birim Fiyat',
      origin: 'Turkiye',
      origin_flag: 'tr',
      description: '',
      market_count: 2,
      repriceable_markets: 49,
      positions: 22494,
      loaded_count: 0,
      variants: [variant(), PARIS],
    },
  ],
};

vi.mock('@/features/costs/baseCatalog', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useBaseCatalog: () => ({ data: CATALOG, error: null, refetch: vi.fn() }) };
});

import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { DatabaseSetupPage } from '../DatabaseSetupPage';

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DatabaseSetupPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DatabaseSetupPage, a national market card', () => {
  const addToast = vi.fn();

  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    addToast.mockReset();
    localStorage.clear();
    apiGet.mockResolvedValue([]);
    apiPost.mockImplementation((path: string) =>
      path.startsWith('/v1/costs/base-market/')
        ? Promise.resolve({ items_repriced: 22494, text_language: 'fr', text_language_requested: 'fr' })
        : Promise.resolve({}),
    );
    useToastStore.setState({ addToast });
  });

  it('prices into the market and never imports the home catalogue beside it', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderPage();

    const button = (await screen.findAllByRole('button')).find((b) => /France/.test(b.textContent ?? ''));
    fireEvent.click(button);

    await waitFor(() =>
      expect(apiPost.mock.calls.map((c) => c[0])).toContain('/v1/costs/base-market/TR_NATIONAL/FR_PARIS_fr'),
    );
    const paths = apiPost.mock.calls.map((c) => c[0]);
    expect(paths.some((p) => p.startsWith('/v1/catalog/import/'))).toBe(false);
    expect(paths.some((p) => p.startsWith('/v1/costs/load-cwicr/'))).toBe(false);

    await waitFor(() => expect(addToast).toHaveBeenCalled());
    const toast = addToast.mock.calls.map((c) => c[0]).find((x) => x.type === 'success');
    expect(toast.title).toMatch(/France/);
  });

  it('does not offer the market card to a viewer', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderPage();

    await screen.findAllByTestId('base-variant-card');
    expect(screen.queryAllByTestId('base-variant-card')).toHaveLength(1);
    expect(screen.queryAllByRole('button').some((b) => /France/.test(b.textContent ?? ''))).toBe(false);
  });
});
