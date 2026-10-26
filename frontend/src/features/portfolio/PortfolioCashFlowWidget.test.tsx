// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Tests for <PortfolioCashFlowWidget>: per-currency blocks, negative projects
// listed with links to the cost model, projects without a forecast.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) =>
      typeof opts === 'object' && opts && 'defaultValue' in opts ? (opts.defaultValue ?? '') : _key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const apiMocks = vi.hoisted(() => ({
  getPortfolioForecast: vi.fn(),
  exportPortfolio: vi.fn(),
}));
vi.mock('@/features/costmodel/cashflowForecastApi', () => ({ cashflowForecastApi: apiMocks }));

import { PortfolioCashFlowWidget } from './PortfolioCashFlowWidget';

afterEach(() => cleanup());

describe('PortfolioCashFlowWidget', () => {
  it('lists negative projects per currency and projects without a forecast', async () => {
    apiMocks.getPortfolioForecast.mockResolvedValue({
      as_of: '2026-10-26',
      scenario: { receipt_delay_days: 0, cost_overrun_pct: '0' },
      currencies: [
        {
          currency: 'EUR',
          months: [],
          closing_position: '-1500',
          peak_funding: { amount: '2500', period: '2026-12' },
          projects: [
            { project_id: 'a', project_name: 'Alpha Tower', closing_position: '-1500', peak_funding: null, negative: true },
            { project_id: 'b', project_name: 'Beta Bridge', closing_position: '900', peak_funding: null, negative: false },
          ],
        },
        {
          currency: 'USD',
          months: [],
          closing_position: '300',
          peak_funding: null,
          projects: [],
        },
      ],
      projects_without_forecast: [{ project_id: 'c', project_name: 'Gamma Road' }],
      findings_count: 1,
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <PortfolioCashFlowWidget />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const eur = await screen.findByTestId('portfolio-cf-EUR');
    expect(within(eur).getByText('Alpha Tower').getAttribute('href')).toBe('/5d');
    expect(within(eur).queryByText('Beta Bridge')).toBeNull();
    expect(eur.textContent).toContain('2026-12');

    const usd = screen.getByTestId('portfolio-cf-USD');
    expect(usd.textContent).not.toContain('Alpha Tower');

    expect(within(screen.getByTestId('portfolio-cf-missing')).getByText('Gamma Road')).toBeTruthy();
  });
});
