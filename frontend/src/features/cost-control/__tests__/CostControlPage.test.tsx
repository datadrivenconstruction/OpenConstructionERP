// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const projectState = { activeProjectId: 'p-1' as string | null, activeProjectName: 'Hotel' };

vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (sel: (s: typeof projectState) => unknown) => sel(projectState),
}));

vi.mock('@/shared/lib/permissionGates', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/permissionGates')>();
  return { ...actual, useHasPermission: () => true };
});

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    costControlApi: {
      report: vi.fn(),
      snapshots: vi.fn(),
      createSnapshot: vi.fn(),
      deleteSnapshot: vi.fn(),
      setForecast: vi.fn(),
      clearForecast: vi.fn(),
      lineHistory: vi.fn(),
      unassigned: vi.fn(),
      assign: vi.fn(),
      chain: vi.fn(),
      setVector: vi.fn(),
      inheritAll: vi.fn(),
      directCost: vi.fn(),
    },
  };
});

vi.mock('../paymentsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../paymentsApi')>();
  const empty = {
    contract_value: '0',
    invoiced: '0',
    invoiced_pct: null,
    released: '0',
    payable: '0',
    paid: '0',
    open_amount: '0',
    retention_held: '0',
    retention_posted: '0',
  };
  return {
    ...actual,
    paymentsApi: {
      ledger: vi.fn().mockResolvedValue({ project_id: 'p-1', currency: 'EUR', contracts: [], other_invoices: [], totals: empty }),
      retention: vi.fn().mockResolvedValue({ project_id: 'p-1', currency: 'EUR', contracts: [], held: '0', posted: '0' }),
      findings: vi.fn().mockResolvedValue({ project_id: 'p-1', findings: [], errors: 0, warnings: 0 }),
    },
  };
});

import { costControlApi, type CostControlReport, type CostControlRow } from '../api';
import { CostControlPage } from '../CostControlPage';

function row(over: Partial<CostControlRow>): CostControlRow {
  return {
    key: 'x',
    kind: 'cost_line',
    code: '',
    description: '',
    account_id: null,
    status: 'active',
    budget: '0',
    estimate: '0',
    planned: '0',
    awarded: '0',
    changes: '0',
    committed: '0',
    measured: '0',
    certified: '0',
    invoiced: '0',
    paid: '0',
    pending_changes: '0',
    forecast: '0',
    forecast_source: 'none',
    automatic_forecast: '0',
    automatic_source: 'none',
    variance: '0',
    variance_pct: null,
    override: null,
    ...over,
  };
}

const REPORT: CostControlReport = {
  project_id: 'p-1',
  currency: 'EUR',
  axis: 'cost_line',
  as_of: '2026-10-17',
  totals: {
    planned: '200000.00',
    forecast: '215000.00',
    variance: '15000.00',
    variance_pct: '7.5',
    certified: '80000.00',
    paid: '60000.00',
    pending_changes: '3000.00',
    pending_count: '1',
    forecast_with_pending: '218000.00',
  },
  rows: [
    row({
      key: 'cl-300',
      code: '300',
      description: 'Building construction',
      planned: '120000.00',
      awarded: '125000.00',
      changes: '10000.00',
      committed: '135000.00',
      certified: '80000.00',
      paid: '60000.00',
      forecast: '135000.00',
      forecast_source: 'awarded',
      variance: '15000.00',
      variance_pct: '12.5',
    }),
    row({
      key: 'cl-400',
      code: '400',
      description: 'Technical installations',
      planned: '80000.00',
      estimate: '80000.00',
      forecast: '80000.00',
      forecast_source: 'estimate',
    }),
    row({
      key: 'unassigned',
      kind: 'unassigned',
      awarded: '7000.00',
      committed: '7000.00',
      forecast: '7000.00',
      forecast_source: 'awarded',
    }),
  ],
  accounts: [],
  findings: [
    {
      rule_id: 'cost_control.forecast_over_plan',
      severity: 'warning',
      line_key: 'cl-300',
      code: '300',
      amount: '15000.00',
      details: { pct: '12.5' },
    },
  ],
  last_snapshot: null,
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/cost-control']}>
        <CostControlPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  projectState.activeProjectId = 'p-1';
  vi.mocked(costControlApi.report).mockResolvedValue(REPORT);
  vi.mocked(costControlApi.chain).mockResolvedValue({ project_id: 'p-1', currency: 'EUR', buckets: [], findings: [] });
  vi.mocked(costControlApi.snapshots).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  vi.mocked(costControlApi.unassigned).mockResolvedValue({
    items: [
      {
        kind: 'contract_line',
        id: 'l-9',
        group_id: 'k-1',
        group_code: 'K1',
        group_title: 'Shell and core',
        code: '01.09',
        description: 'Scaffolding',
        amount: '7000.00',
      },
    ],
    total: 1,
    offset: 0,
    limit: 500,
  });
});

describe('CostControlPage', () => {
  it('asks for a project when none is open', () => {
    projectState.activeProjectId = null;
    renderPage();
    expect(screen.getByText('Open a project first')).toBeInTheDocument();
    expect(costControlApi.report).not.toHaveBeenCalled();
  });

  it('shows every cost line with where its forecast comes from', async () => {
    renderPage();
    const table = await screen.findByTestId('cost-control-table');
    expect(within(table).getByText('Building construction')).toBeInTheDocument();
    expect(within(table).getByText('Technical installations')).toBeInTheDocument();
    expect(within(table).getAllByText('Award + changes').length).toBeGreaterThan(0);
    expect(within(table).getAllByText('Estimate').length).toBeGreaterThan(0);
    expect(within(table).getByText('Project total')).toBeInTheDocument();
    expect(costControlApi.report).toHaveBeenCalledWith('p-1', 'cost_line');
  });

  it('turns a validation finding into a plain sentence', async () => {
    renderPage();
    expect(await screen.findByText('300: forecast 12.5% above plan')).toBeInTheDocument();
  });

  it('filters down to the lines above plan', async () => {
    renderPage();
    const table = await screen.findByTestId('cost-control-table');
    fireEvent.click(screen.getByRole('checkbox', { name: /only lines above plan/i }));
    await waitFor(() => expect(within(table).queryByText('Technical installations')).not.toBeInTheDocument());
    expect(within(table).getByText('Building construction')).toBeInTheDocument();
  });

  it('asks for the stage before saving a forecast', async () => {
    renderPage();
    await screen.findByTestId('cost-control-table');
    fireEvent.click(screen.getAllByRole('button', { name: /save forecast/i })[0]!);
    expect(await screen.findByText('What does this forecast mark?')).toBeInTheDocument();
  });

  it('opens the lines behind the unassigned row, ready to be put on a cost line', async () => {
    renderPage();
    await screen.findByTestId('cost-control-table');
    fireEvent.click(screen.getByTestId('cost-control-row-unassigned'));
    expect(await screen.findByText('Put the money on cost lines')).toBeInTheDocument();
    expect(await screen.findByText('Scaffolding')).toBeInTheDocument();
    expect(screen.getByText('K1 Shell and core')).toBeInTheDocument();
    expect(screen.getByTestId('assign-l-9')).toBeInTheDocument();
    expect(costControlApi.unassigned).toHaveBeenCalledWith('p-1');
  });
});
