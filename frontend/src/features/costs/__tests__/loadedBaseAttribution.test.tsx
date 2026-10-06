// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A base published under CC BY (the Toscana prezzario) has to keep its credit
// where it is used, not only on the card that loads it. The installed-databases
// row is where a loaded base lives from then on, so the credit is asserted
// there, and asserted absent from a row whose family names no attribution.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn() };
});

import { apiGet } from '@/shared/lib/api';
import { LoadedDatabasesSection } from '../ImportDatabasePage';

const ATTRIBUTION = 'Regione Toscana, Prezzario dei Lavori Pubblici della Toscana, edizione 2026';

function variant(region: string) {
  return {
    region,
    variant_id: region,
    base_region: region,
    market_catalog: '',
    active: false,
    market: 'Italy',
    city: 'National',
    language: 'Italiano',
    lang_code: 'it',
    currency: 'EUR',
    flag: 'it',
    positions: 1,
    bundled: false,
    coefficient: false,
    loaded: true,
    loaded_positions: 1,
  };
}

const CATALOG = {
  repo: 'x',
  total_bases: 2,
  total_families: 2,
  loaded_regions: ['IT_TOSCANA', 'IT_ROME'],
  families: [
    {
      key: 'italy',
      name: 'Italy',
      norm_system: 'Prezzario',
      origin: 'IT',
      origin_flag: 'it',
      description: '',
      market_count: 1,
      repriceable_markets: 0,
      positions: 1,
      loaded_count: 1,
      variants: [variant('IT_TOSCANA')],
      attribution: ATTRIBUTION,
      licence: 'CC BY 4.0',
    },
    {
      key: 'cwicr',
      name: 'CWICR',
      norm_system: 'CWICR',
      origin: '',
      origin_flag: '',
      description: '',
      market_count: 1,
      repriceable_markets: 0,
      positions: 1,
      loaded_count: 1,
      variants: [variant('IT_ROME')],
      attribution: null,
      licence: null,
    },
  ],
};

function mount() {
  apiGet.mockImplementation((url: string) => {
    if (url.includes('/regions/stats/')) {
      return Promise.resolve([
        { region: 'IT_TOSCANA', count: 120 },
        { region: 'IT_ROME', count: 340 },
      ]);
    }
    if (url.includes('/base-catalog/')) return Promise.resolve(CATALOG);
    return Promise.resolve(null);
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <LoadedDatabasesSection />
    </QueryClientProvider>,
  );
}

describe('installed databases credit a base whose licence asks for it', () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it('shows the source and licence on the Toscana row and on no other', async () => {
    mount();
    const credits = await screen.findAllByTestId('loaded-base-attribution');
    expect(credits).toHaveLength(1);
    expect(credits[0].textContent).toContain(ATTRIBUTION);
    expect(credits[0].textContent).toContain('CC BY 4.0');
    expect(credits[0].closest('tr').textContent).toContain('Toscana');
  });
});
