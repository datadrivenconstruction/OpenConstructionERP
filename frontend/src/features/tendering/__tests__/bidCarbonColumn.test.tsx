// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The optional CO2 column of the bid comparison: off by default, and when
// switched on it shows tCO2e per line and in total from POST /carbon/bid-carbon.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, second?: unknown) => {
      if (typeof second === 'string') return second;
      if (second && typeof second === 'object' && 'defaultValue' in second) {
        return String((second as { defaultValue?: string }).defaultValue ?? key);
      }
      return key;
    },
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
  I18nextProvider: ({ children }: { children: unknown }) => children,
  Trans: ({ children }: { children?: unknown }) => children ?? null,
}));

const carbonMocks = vi.hoisted(() => ({ getBidCarbon: vi.fn() }));
vi.mock('@/features/carbon/lifecycleApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/carbon/lifecycleApi')>()),
  ...carbonMocks,
}));

globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const { BidComparisonTable } = await import('../TenderingPage');

const bid = (id: string, rate: number) => ({
  company_name: id,
  bid_id: id,
  unit_rate: rate,
  total: rate * 10,
  deviation_pct: 0,
  priced: true,
});

const comparison = {
  package_id: 'pkg',
  package_name: 'Shell',
  bid_count: 1,
  bid_companies: ['Alpha'],
  budget_total: 1000,
  rows: [
    {
      position_id: 'p1',
      description: 'Slab concrete',
      unit: 'm3',
      budget_quantity: 10,
      budget_rate: 100,
      budget_total: 1000,
      bids: [bid('Alpha', 95)],
    },
  ],
  bid_totals: [
    { bid_id: 'Alpha', company_name: 'Alpha', total: 950, currency: 'EUR', deviation_pct: -5, status: 'submitted',
      matched_lines: 1, total_lines: 1 },
  ],
};

afterEach(() => {
  cleanup();
  carbonMocks.getBidCarbon.mockReset();
});

describe('bid comparison CO2 column', () => {
  it('is hidden and not requested until switched on', () => {
    const view = render(<BidComparisonTable comparison={comparison} currency="EUR" />);
    expect(view.queryByText('CO2, t')).toBeNull();
    expect(carbonMocks.getBidCarbon).not.toHaveBeenCalled();
  });

  it('shows tCO2e per line and in total when switched on', async () => {
    carbonMocks.getBidCarbon.mockResolvedValue({
      lines: [{ ref: 'p1', carbon_kg: '3100', status: 'ok' }],
      total_kg: '3100',
    });
    const view = render(<BidComparisonTable comparison={comparison} currency="EUR" />);
    fireEvent.click(view.getByLabelText('Show CO2 column'));
    expect(view.getByText('CO2, t')).toBeTruthy();
    await waitFor(() => expect(view.getAllByText('3.1').length).toBe(2));
    expect(carbonMocks.getBidCarbon).toHaveBeenCalledWith([
      { ref: 'p1', position_id: 'p1', quantity: 10, unit: 'm3' },
    ]);
  });
});
