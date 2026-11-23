// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ForecastInsightsPanel — predictive analytics panel coverage (TOP-30 #19).
 *
 * Asserts:
 *   1. Loading state renders the spinner before data arrives.
 *   2. A fully-populated forecast renders the CPI/SPI/EAC/VAC tiles, the
 *      schedule finish-variance + at-risk counts, the risk score/band/
 *      confidence and the rationale bullets, plus the always-on
 *      "forecast - review required" disclaimer.
 *   3. A degraded forecast (no EVM snapshot, no schedule) renders the
 *      graceful empty states instead of the tiles.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ForecastInsightsPanel } from '../components/ForecastInsightsPanel';

// Mock the API client — the panel only calls apiGet.
const apiGet = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
}));

// Render MoneyDisplay as a plain span so we can assert on amounts without
// pulling in the preferences store / Intl formatting.
vi.mock('@/shared/ui/MoneyDisplay', () => ({
  MoneyDisplay: ({ amount }: { amount: number | string }) => (
    <span>{String(amount)}</span>
  ),
}));

const FULL_FORECAST = {
  project_id: 'p1',
  project_name: 'Tower',
  currency: 'EUR',
  generated_at: '2026-06-04T00:00:00Z',
  cost: {
    available: true,
    reason: null,
    currency: 'EUR',
    snapshot_date: '2026-06-01',
    bac: '1000000.00',
    ev: '600000.00',
    ac: '700000.00',
    pv: '630000.00',
    cpi: 0.8571,
    spi: 0.9524,
    eac: '1166666.67',
    etc: '466666.67',
    vac: '-166666.67',
    tcpi: '1.3333',
    eac_over_bac: 1.1667,
  },
  schedule: {
    available: true,
    reason: null,
    activities_total: 2,
    activities_complete: 0,
    planned_pct_complete: 41.0,
    actual_pct_complete: 27.5,
    baseline_finish: '2026-12-31',
    forecast_finish: '2027-08-01',
    finish_variance_days: 213,
    at_risk_task_count: 2,
  },
  risk: {
    score: 0.62,
    band: 'amber',
    confidence: 1.0,
    rationale: [
      'Cost performance index is below plan (CPI 0.86).',
      '2 open high-severity risks without mitigation.',
    ],
  },
  review_required: true,
};

const DEGRADED_FORECAST = {
  project_id: 'p2',
  project_name: 'Bare',
  currency: 'EUR',
  generated_at: '2026-06-04T00:00:00Z',
  cost: { available: false, reason: 'no_evm_snapshot', currency: 'EUR' },
  schedule: { available: false, reason: 'no_schedule', activities_total: 0, at_risk_task_count: 0 },
  risk: { score: 0.0, band: 'green', confidence: 0.2, rationale: ['No cost or schedule pressure detected.'] },
  review_required: true,
};

describe('ForecastInsightsPanel', () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it('shows the loading state before data resolves', () => {
    // Never resolves — keeps the panel in its loading branch.
    apiGet.mockReturnValue(new Promise(() => {}));
    render(<ForecastInsightsPanel projectId="p1" />);
    expect(screen.getByTestId('forecast-insights-loading')).toBeInTheDocument();
  });

  it('renders cost tiles, schedule slip, risk gauge and rationale', async () => {
    apiGet.mockResolvedValue(FULL_FORECAST);
    render(<ForecastInsightsPanel projectId="p1" />);

    await waitFor(() =>
      expect(screen.getByTestId('forecast-insights-panel')).toBeInTheDocument(),
    );

    // Always-on disclaimer.
    expect(screen.getByTestId('forecast-insights-disclaimer')).toBeInTheDocument();

    // Cost tiles.
    expect(screen.getByTestId('forecast-insights-cpi')).toHaveTextContent('0.86');
    expect(screen.getByTestId('forecast-insights-spi')).toHaveTextContent('0.95');
    expect(screen.getByTestId('forecast-insights-eac')).toHaveTextContent('1166666.67');
    expect(screen.getByTestId('forecast-insights-vac')).toHaveTextContent('-166666.67');

    // Schedule slip.
    expect(screen.getByTestId('forecast-insights-schedule')).toBeInTheDocument();
    expect(screen.getByTestId('forecast-insights-at-risk')).toHaveTextContent('2 / 2');

    // Risk gauge: score is 0.62 → 62; amber band; confidence 100%.
    expect(screen.getByTestId('forecast-insights-risk-score')).toHaveTextContent('62');
    expect(screen.getByTestId('forecast-insights-risk-band')).toBeInTheDocument();
    expect(screen.getByTestId('forecast-insights-confidence')).toBeInTheDocument();

    // Rationale bullets — both lines rendered.
    const rationale = screen.getByTestId('forecast-insights-rationale');
    expect(rationale).toHaveTextContent('Cost performance index is below plan');
    expect(rationale).toHaveTextContent('open high-severity risks');

    // Called the live forecast endpoint.
    expect(apiGet).toHaveBeenCalledWith('/v1/project-intelligence/p1/forecast');
  });

  it('renders graceful empty states when sources are missing', async () => {
    apiGet.mockResolvedValue(DEGRADED_FORECAST);
    render(<ForecastInsightsPanel projectId="p2" />);

    await waitFor(() =>
      expect(screen.getByTestId('forecast-insights-panel')).toBeInTheDocument(),
    );

    // Cost + schedule degrade; tiles are NOT rendered.
    expect(screen.getByTestId('forecast-insights-cost-degraded')).toBeInTheDocument();
    expect(screen.getByTestId('forecast-insights-schedule-degraded')).toBeInTheDocument();
    expect(screen.queryByTestId('forecast-insights-cost-tiles')).not.toBeInTheDocument();

    // Risk still renders deterministically (green, rationale present).
    expect(screen.getByTestId('forecast-insights-risk-score')).toHaveTextContent('0');
    expect(screen.getByTestId('forecast-insights-rationale')).toBeInTheDocument();
  });

  it('shows forecast findings when present and hides the block when empty', async () => {
    apiGet.mockResolvedValue({
      ...FULL_FORECAST,
      findings: [{ rule_id: 'pi.x', severity: 'warning', message: 'CPI is implausible', params: { cpi: 42 } }],
    });
    const { unmount } = render(<ForecastInsightsPanel projectId="p1" />);
    await waitFor(() => expect(screen.getByTestId('forecast-insights-findings')).toBeInTheDocument());
    expect(screen.getByText(/CPI is implausible/)).toBeInTheDocument();
    unmount();

    apiGet.mockResolvedValue({ ...FULL_FORECAST, findings: [] });
    render(<ForecastInsightsPanel projectId="p1" />);
    await waitFor(() => expect(screen.getByTestId('forecast-insights-cost-tiles')).toBeInTheDocument());
    expect(screen.queryByTestId('forecast-insights-findings')).not.toBeInTheDocument();
  });
});
