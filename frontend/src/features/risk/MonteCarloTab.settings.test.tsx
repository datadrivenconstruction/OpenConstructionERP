// The confidence level and the range for single-figure risks are editable,
// validated, sent with the run, and restored from the last stored run.
//
// The test setup's i18n mock renders each label's English defaultValue.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

import * as api from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { MonteCarloTab, parseBounded } from './MonteCarloTab';
import type { RiskSimulationResult } from './api';

const getMock = vi.mocked(api.apiGet);
const postMock = vi.mocked(api.apiPost);

function run(extra: Partial<RiskSimulationResult> = {}): RiskSimulationResult {
  return {
    iterations: 10000,
    risk_count: 3,
    mode: 'cost',
    p50_cost: '120000.00',
    p80_cost: '120000.00',
    p90_cost: '120000.00',
    p95_cost: '120000.00',
    target_cost: '120000.00',
    p50_schedule_days: null,
    p80_schedule_days: null,
    p90_schedule_days: null,
    p95_schedule_days: null,
    target_schedule_days: null,
    histogram_bins: [],
    tornado: [],
    currency: 'USD',
    confidence: 80,
    range_low_pct: 0,
    range_high_pct: 0,
    point_estimate_risks: 3,
    ...extra,
  };
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MonteCarloTab projectId="p-1" currency="USD" />
    </QueryClientProvider>,
  );
}

const runButton = () => screen.getByRole('button', { name: /run simulation/i });

describe('Monte Carlo settings', () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockResolvedValue(null);
    useAuthStore.setState({ userRole: 'editor' });
  });

  it('reads typed bounds strictly', () => {
    expect(parseBounded('80', 50, 99, true)).toBe(80);
    expect(parseBounded('49', 50, 99, true)).toBeNull();
    expect(parseBounded('100', 50, 99, true)).toBeNull();
    expect(parseBounded('85.5', 50, 99, true)).toBeNull();
    expect(parseBounded('12,5', 0, 90)).toBe(12.5);
    expect(parseBounded('-5', 0, 90)).toBeNull();
    expect(parseBounded('abc', 0, 90)).toBeNull();
  });

  it('sends the chosen confidence and range with the run', async () => {
    postMock.mockResolvedValue(run({ confidence: 90, range_low_pct: 10, range_high_pct: 25, target_cost: '131000.00' }));
    renderTab();
    fireEvent.change(screen.getByLabelText(/confidence level/i), { target: { value: '90' } });
    fireEvent.change(screen.getByLabelText(/below the figure/i), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText(/above the figure/i), { target: { value: '25' } });
    fireEvent.click(runButton());
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        '/v1/risk/projects/p-1/simulate',
        expect.objectContaining({ confidence: 90, range_low_pct: 10, range_high_pct: 25 }),
      ),
    );
    expect(await screen.findByText('P90 Cost (plan)')).toBeInTheDocument();
    expect(screen.getByTestId('mc-ran-at')).toHaveTextContent('P90');
  });

  it('blocks the run and says why when a value is out of bounds', () => {
    renderTab();
    fireEvent.change(screen.getByLabelText(/confidence level/i), { target: { value: '120' } });
    expect(screen.getByText('Enter a whole number from 50 to 99.')).toBeInTheDocument();
    expect(runButton()).toBeDisabled();
    expect(runButton()).toHaveAttribute('title', 'Correct the highlighted settings first.');
  });

  it('restores the last run and explains why fixed single-figure risks give equal percentiles', async () => {
    getMock.mockResolvedValue(run());
    renderTab();
    expect(await screen.findByTestId('mc-point-warning')).toHaveTextContent('Risks with a single figure: 3 of 3');
    expect(screen.getByTestId('mc-explainer')).toHaveTextContent('At P80, 80 of every 100 runs');
    fireEvent.change(screen.getByLabelText(/above the figure/i), { target: { value: '30' } });
    expect(screen.getByText(/settings differ from the last run/i)).toBeInTheDocument();
  });
});
