// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// <PriceListsPanel /> shows the list (gross) price, the discount and the net price side by
// side, flags an expired list, and names the import row errors the validators raise.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => {
  type Opts = Record<string, unknown>;
  const fill = (template: string, opts?: Opts): string => {
    if (!opts) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
      opts[name] === undefined ? `{{${name}}}` : String(opts[name]),
    );
  };
  return {
    useTranslation: () => ({
      t: (key: string, second?: string | Opts, third?: Opts) => {
        if (typeof second === 'string') return fill(second, third);
        const dflt = second?.defaultValue;
        return fill(typeof dflt === 'string' ? dflt : key, second);
      },
      i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
    Trans: ({ children }: { children?: unknown }) => children ?? null,
    initReactI18next: { type: '3rdParty', init: () => undefined },
    I18nextProvider: ({ children }: { children?: unknown }) => children ?? null,
  };
});

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return { ...actual, listVendorPriceLists: vi.fn(), listPriceListEntries: vi.fn() };
});

import { listPriceListEntries, listVendorPriceLists, type Vendor } from './api';
import { PriceListsPanel, rowError } from './PriceListsPanel';

const vendor = { id: 'v1', code: 'ACME', name: 'Acme', status: 'active', currency: 'EUR' } as Vendor;

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PriceListsPanel vendors={[vendor]} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('PriceListsPanel', () => {
  it('shows gross, discount and net, and flags an expired list', async () => {
    vi.mocked(listVendorPriceLists).mockResolvedValue([
      { id: 'pl1', vendor_id: 'v1', name: 'Spring', valid_from: '2025-01-01', valid_to: '2025-12-31',
        currency: 'EUR', status: 'active', uploaded_by: null, entry_count: 1, expired: true },
    ]);
    vi.mocked(listPriceListEntries).mockResolvedValue({
      price_list: { id: 'pl1', vendor_id: 'v1', name: 'Spring', valid_from: null, valid_to: null,
        currency: 'EUR', status: 'active', uploaded_by: null, expired: true },
      items: [{
        entry_id: 'e1', catalog_item_id: 'i1', sku: 'CEM-25', name: 'Cement', unit_of_measure: 'bag',
        vendor_sku: 'A-1', mpn: null, gtin: null, gross_price: '10.0000', net_price: '8.5000',
        discount_pct: '15', discount_source: 'overall', discount_agreement_id: 'd1',
        min_order_qty: '1', lead_time_days: 2, product_url: null, attachment_count: 0,
      }],
      total: 1, offset: 0, limit: 200,
    });
    renderPanel();
    await waitFor(() => expect(screen.getByText('CEM-25')).toBeTruthy());
    expect(screen.getByText('-15 %')).toBeTruthy();
    expect(screen.getByText('Expired: not used for new orders')).toBeTruthy();
  });

  it('names every import row error', () => {
    const t = ((k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k) as never;
    expect(rowError(t, 'missing_price')).toBe('no price');
    expect(rowError(t, 'negative_price')).toBe('negative price');
    expect(rowError(t, 'unknown_unit')).toBe('unit not recognised');
    expect(rowError(t, 'discount_out_of_range')).toBe('discount must be 0 to 100');
    expect(rowError(t, 'duplicate_vendor_sku')).toBe('vendor SKU repeats in the file');
  });
});
