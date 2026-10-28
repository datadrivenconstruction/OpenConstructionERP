// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// <CostBenchmarksPage />: renders a compare result, highlights the outlier
// rows (below / above the band) and shows the low-confidence badge.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api', () => ({
  fetchRecords: vi.fn(),
  createRecord: vi.fn(),
  deleteRecord: vi.fn(),
  captureProject: vi.fn(),
  compareEstimate: vi.fn(),
  downloadAnonymised: vi.fn(),
}));

import { fetchRecords, compareEstimate } from '../api';
import type { BenchmarkRecord, CompareResult } from '../api';
import CostBenchmarksPage from '../CostBenchmarksPage';

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

function record(over: Partial<BenchmarkRecord>): BenchmarkRecord {
  return {
    id: 'r1',
    kind: 'completed',
    project_id: null,
    name: 'School A',
    project_type: 'school',
    country: 'DE',
    region: '',
    currency: 'EUR',
    cost_date: '2024-05-01',
    standard: 'din276',
    gfa_m2: '1000',
    functional_unit: 'm2',
    functional_units: null,
    total_cost: '2500000',
    is_synthetic: false,
    source: 'own',
    elements: [],
    ...over,
  };
}

const band = (p10: string, p50: string, p90: string) => ({ count: 3, p10, p50, p90 });

const RESULT: CompareResult = {
  estimate: {
    id: 'e1',
    name: 'School B estimate',
    project_type: 'school',
    country: 'DE',
    gfa_m2: '1200',
    functional_unit: 'm2',
    functional_units: null,
    total: '3300000',
    total_per_unit: '2750',
    total_position: 'within',
  },
  measure: 'gfa',
  basis: {
    base_date: '2026-01-01',
    base_region: 'DE',
    reporting_currency: 'EUR',
    index_series: 'bki',
    index_latest_period: '2026-Q2',
    fx_rate_date: '2026-01-01',
    location_factors: true,
    stale: true,
  },
  cohort: {
    count: 3,
    min_projects: 5,
    low_confidence: true,
    source: 'own',
    reference_source: null,
    missing_quantity: [],
    projects: [],
  },
  total_band: band('2300', '2500', '2700'),
  elements: [
    { code: '300', label: 'Structure', estimate_per_unit: '1200', estimate_amount: '1440000', band: band('900', '1000', '1100'), band_source: 'own', position: 'above' },
    { code: '400', label: 'Services', estimate_per_unit: '700', estimate_amount: '840000', band: band('600', '700', '800'), band_source: 'own', position: 'within' },
    { code: '500', label: 'External works', estimate_per_unit: '50', estimate_amount: '60000', band: band('100', '150', '200'), band_source: 'own', position: 'below' },
  ],
  findings: [{ rule_id: 'cost_benchmarks.outlier', severity: 'warning', message: 'Structure is above the P90 of the cohort.', element_ref: '300' }],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CostBenchmarksPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  asMock(fetchRecords).mockImplementation(async ({ kind }: { kind: string }) =>
    kind === 'completed'
      ? [record({})]
      : [record({ id: 'e1', kind: 'estimate', name: 'School B estimate' })],
  );
  asMock(compareEstimate).mockResolvedValue(RESULT);
});

afterEach(() => cleanup());

describe('<CostBenchmarksPage />', () => {
  it('lists completed records with cost per m2', async () => {
    renderPage();
    await waitFor(() => expect(screen.getAllByTestId('record-row').length).toBeGreaterThan(0));
    expect(screen.getAllByText('School A').length).toBeGreaterThan(0);
  });

  it('renders a compare result, marks the two outlier rows and the low-confidence badge', async () => {
    renderPage();
    const select = await screen.findByRole('combobox', { name: 'Estimate' });
    await waitFor(() => expect(screen.getAllByRole('option', { name: 'School B estimate' }).length).toBe(1));
    fireEvent.change(select, { target: { value: 'e1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));

    await waitFor(() => expect(compareEstimate).toHaveBeenCalled());
    expect(asMock(compareEstimate).mock.calls[0]?.[0]).toMatchObject({ estimate_id: 'e1', measure: 'gfa', min_projects: 5 });

    expect(await screen.findByTestId('low-confidence')).toBeTruthy();
    expect(screen.getByTestId('stale-index')).toBeTruthy();
    expect(screen.getByTestId('band-row-300').getAttribute('data-position')).toBe('above');
    expect(screen.getByTestId('band-row-500').getAttribute('data-position')).toBe('below');
    expect(screen.getByTestId('band-row-400').getAttribute('data-position')).toBe('within');
    // Outlier rows carry the highlight class, the in-range row does not.
    expect(screen.getByTestId('band-row-300').className).toContain('bg-semantic-error-bg');
    expect(screen.getByTestId('band-row-500').className).toContain('bg-semantic-error-bg');
    expect(screen.getByTestId('band-row-400').className).not.toContain('bg-semantic-error-bg');
    expect(screen.getByText('Structure is above the P90 of the cohort.')).toBeTruthy();
    expect(screen.getByText('Band from your own history')).toBeTruthy();
  });
});
