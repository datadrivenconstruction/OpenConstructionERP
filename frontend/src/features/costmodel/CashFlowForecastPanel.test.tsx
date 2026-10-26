// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Tests for <CashFlowForecastPanel>: peak funding card, per-currency
// separation, scenario inputs feeding the query, and the empty state.

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import type { CurrencyForecast, ProjectCashFlowForecast } from './cashflowForecastApi';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string } & Record<string, unknown>) => {
      if (typeof opts === 'object' && opts && 'defaultValue' in opts) {
        let dv = opts.defaultValue ?? '';
        for (const [k, v] of Object.entries(opts)) {
          if (k === 'defaultValue') continue;
          dv = dv.replaceAll(`{{${k}}}`, String(v));
        }
        return dv;
      }
      return _key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const toastMocks = vi.hoisted(() => ({ addToastMock: vi.fn() }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: { addToast: typeof toastMocks.addToastMock }) => unknown) =>
      selector({ addToast: toastMocks.addToastMock }),
    { getState: () => ({ addToast: toastMocks.addToastMock }) },
  ),
}));

const apiMocks = vi.hoisted(() => ({
  getProjectForecast: vi.fn(),
  exportProject: vi.fn(),
}));
vi.mock('./cashflowForecastApi', () => ({ cashflowForecastApi: apiMocks }));

import { CashFlowForecastPanel } from './CashFlowForecastPanel';

function currency(code: string, peak: string | null, closing: string): CurrencyForecast {
  return {
    currency: code,
    months: [
      {
        period: '2026-11',
        is_past: false,
        planned_in: '0',
        planned_out: '5000',
        actual_in: '0',
        actual_out: '0',
        expected_in: '1000',
        expected_out: '5000',
        net: '-4000',
        cumulative: '-4000',
        variance_in: '0',
        variance_out: '0',
      },
    ],
    totals: {
      planned_in: '0',
      planned_out: '5000',
      actual_in: '0',
      actual_out: '0',
      expected_in: '1000',
      expected_out: '5000',
    },
    sources: [{ source: 'purchase_order', direction: 'out', amount: '5000' }],
    closing_position: closing,
    peak_funding: peak ? { amount: peak, period: '2026-11' } : null,
  };
}

function forecast(over: Partial<ProjectCashFlowForecast> = {}): ProjectCashFlowForecast {
  return {
    project_id: 'p1',
    project_name: 'Tower',
    as_of: '2026-10-26',
    scenario: { receipt_delay_days: 0, cost_overrun_pct: '0' },
    threshold: '0',
    has_inputs: true,
    currencies: [currency('EUR', '4000', '-4000'), currency('USD', '7777', '-7777')],
    findings: [],
    ...over,
  };
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CashFlowForecastPanel projectId="p1" />
    </QueryClientProvider>,
  );
}

describe('CashFlowForecastPanel', () => {
  beforeEach(() => {
    apiMocks.getProjectForecast.mockReset();
  });
  afterEach(() => cleanup());

  it('shows peak funding per currency and never mixes currencies', async () => {
    apiMocks.getProjectForecast.mockResolvedValue(forecast());
    renderPanel();

    const peak = await screen.findByTestId('cf-peak-funding');
    expect(peak.textContent).toContain('4,000');
    expect(peak.textContent).toContain('2026-11');
    expect(peak.textContent).not.toContain('7,777');

    fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'USD' } });
    await waitFor(() => expect(screen.getByTestId('cf-peak-funding').textContent).toContain('7,777'));
    expect(screen.getByTestId('cf-peak-funding').textContent).not.toContain('4,000');
  });

  it('feeds scenario inputs into the query', async () => {
    apiMocks.getProjectForecast.mockResolvedValue(forecast());
    renderPanel();
    await screen.findByTestId('cf-peak-funding');

    fireEvent.change(screen.getByLabelText('Receipt delay (days)'), { target: { value: '30' } });
    fireEvent.change(screen.getByLabelText('Cost overrun (%)'), { target: { value: '10' } });

    await waitFor(() =>
      expect(apiMocks.getProjectForecast).toHaveBeenLastCalledWith('p1', {
        receiptDelayDays: '30',
        costOverrunPct: '10',
      }),
    );
  });

  it('renders the empty state when there are no inputs', async () => {
    apiMocks.getProjectForecast.mockResolvedValue(forecast({ has_inputs: false, currencies: [] }));
    renderPanel();
    expect(await screen.findByText('No cash-flow inputs yet')).toBeTruthy();
    expect(screen.queryByTestId('cf-peak-funding')).toBeNull();
  });
});
