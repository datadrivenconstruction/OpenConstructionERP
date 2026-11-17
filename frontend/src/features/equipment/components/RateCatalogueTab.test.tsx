// @ts-nocheck
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const catalogue = vi.hoisted(() => ({
  id: 'c1', family_id: 'f1', name: 'Demo rates EUR', source_label: '', licence_note: '', currency: 'EUR',
  valid_from: '2027-01-01', interest_convention: 'average_value', is_synthetic: true, superseded: false, machines: 1,
}));

vi.mock('../ratesApi', async () => {
  const actual = await vi.importActual('../ratesApi');
  return {
    ...actual,
    listRateCatalogues: vi.fn().mockResolvedValue({ items: [catalogue], total: 1, offset: 0, limit: 500 }),
    getRateCatalogue: vi.fn().mockResolvedValue({
      ...catalogue,
      items: [{
        id: 'i1', catalogue_id: 'c1', code: 'E-20', name: 'Demo excavator 20 t', category: 'Earthwork', size_key: '20t',
        value: '180000.00', residual: '18000.00', life_years: '6', months_per_year: '10', interest: '0.06',
        repair: '0.6', hours_per_month: '170', override_monthly_rate: null, is_synthetic: true,
      }],
    }),
    loadDemoCatalogue: vi.fn(),
    previewRate: vi.fn(),
  };
});

import { RateCatalogueTab } from './RateCatalogueTab';
import { fractionToPercent, percentToFraction } from '../ratesApi';

describe('rate catalogue', () => {
  it('shows the demo chip and the invented-numbers note for a synthetic catalogue', async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <RateCatalogueTab />
      </QueryClientProvider>,
    );
    await screen.findByText('Demo excavator 20 t');
    expect(screen.getByText('Demo values')).toBeTruthy();
    expect(screen.getByText(/invented numbers/i)).toBeTruthy();
  });

  it('keeps interest and repair as fractions on the wire and percent on screen', () => {
    expect(fractionToPercent('0.06')).toBe('6');
    expect(fractionToPercent('0.6')).toBe('60');
    expect(percentToFraction('6')).toBe('0.06');
    expect(percentToFraction('')).toBeNull();
  });
});
