// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Capital plan page: the gap row turns red where demand passes the budget, the
// arrows move an item's spend to another column, an empty scenario offers the
// import, and a funding suggestion is shown before it is applied.

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('./api', () => ({
  capitalPlanApi: {
    listPlans: vi.fn(),
    createPlan: vi.fn(),
    listEnvelopes: vi.fn(),
    replaceEnvelopes: vi.fn(),
    listScenarios: vi.fn(),
    cloneScenario: vi.fn(),
    deleteScenario: vi.fn(),
    listItems: vi.fn(),
    patchItem: vi.fn(),
    applyStatuses: vi.fn(),
    importProjects: vi.fn(),
    summary: vi.fn(),
    autofund: vi.fn(),
    compare: vi.fn(),
    exportXlsx: vi.fn(),
  },
}));

import { capitalPlanApi } from './api';
import { CapitalPlanPage } from './CapitalPlanPage';

const api = capitalPlanApi as unknown as Record<'listPlans' | 'listScenarios' | 'listEnvelopes' | 'listItems' | 'summary' | 'patchItem' | 'importProjects' | 'autofund' | 'applyStatuses', ReturnType<typeof vi.fn>>;

const PLAN = { id: 'plan1', node_id: null, name: 'Five-year plan', currency: 'EUR', start_year: 2030, horizon_years: 3 };
const BASE = { id: 'sc1', plan_id: 'plan1', name: 'Baseline', is_baseline: true, notes: '' };
const ITEM = {
  id: 'it1',
  scenario_id: 'sc1',
  project_id: null,
  title: 'Road resurfacing',
  priority: 2,
  start_year: 2030,
  duration_years: 1,
  total_cost: '150',
  phasing: [],
  status: 'proposed',
  score: null,
};

function summaryFor(startYear: number) {
  const spend = (y: number) => (y === startYear ? '150.00' : '0.00');
  const years = [2030, 2031, 2032];
  let cumulative = 0;
  return {
    years,
    rows: years.map((y) => {
      const gap = 100 - Number(spend(y));
      cumulative += gap;
      return {
        year: y,
        demand: spend(y),
        envelope: '100.00',
        gap: gap.toFixed(2),
        cumulative_gap: cumulative.toFixed(2),
      };
    }),
    items: [
      {
        id: 'it1',
        spend: Object.fromEntries(years.map((y) => [String(y), spend(y)])),
        outside_horizon: '0.00',
      },
    ],
    totals: {},
    unfunded: ['it1'],
    findings: [],
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CapitalPlanPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CapitalPlanPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listPlans.mockResolvedValue([PLAN]);
    api.listScenarios.mockResolvedValue([BASE]);
    api.listEnvelopes.mockResolvedValue([
      { id: 'e1', plan_id: 'plan1', year: 2030, amount: '100.00', label: '' },
      { id: 'e2', plan_id: 'plan1', year: 2031, amount: '100.00', label: '' },
      { id: 'e3', plan_id: 'plan1', year: 2032, amount: '100.00', label: '' },
    ]);
    api.listItems.mockResolvedValue([ITEM]);
    api.summary.mockResolvedValue(summaryFor(2030));
  });

  it('paints the gap red only in the year that is over the budget', async () => {
    renderPage();
    const over = await screen.findByTestId('gap-2030');
    await waitFor(() => expect(over).toHaveAttribute('data-tone', 'short'));
    expect(over.className).toContain('text-semantic-error');
    expect(screen.getByTestId('gap-2031')).toHaveAttribute('data-tone', 'ok');
    expect(screen.getByTestId('gap-2031').className).not.toContain('text-semantic-error');
    expect(screen.getByTestId('gap-2032')).toHaveAttribute('data-tone', 'ok');
  });

  it('moves the spend to the next column when the item is delayed a year', async () => {
    api.patchItem.mockResolvedValue({ ...ITEM, start_year: 2031 });
    renderPage();
    await waitFor(() => expect(screen.getByTestId('cell-it1-2030').textContent).not.toBe('-'));
    expect(screen.getByTestId('cell-it1-2031').textContent).toBe('-');

    // The server answers the next read with the shifted spend.
    api.summary.mockResolvedValue(summaryFor(2031));
    fireEvent.click(screen.getByTestId('later-it1'));

    await waitFor(() => expect(api.patchItem).toHaveBeenCalledWith('it1', { start_year: 2031 }));
    await waitFor(() => expect(screen.getByTestId('cell-it1-2030').textContent).toBe('-'));
    expect(screen.getByTestId('cell-it1-2031').textContent).not.toBe('-');
    await waitFor(() => expect(screen.getByTestId('gap-2030')).toHaveAttribute('data-tone', 'ok'));
    expect(screen.getByTestId('gap-2031')).toHaveAttribute('data-tone', 'short');
  });

  it('offers the import when the scenario has no projects', async () => {
    api.listItems.mockResolvedValue([]);
    api.summary.mockResolvedValue({ ...summaryFor(2030), items: [], unfunded: [] });
    api.importProjects.mockResolvedValue({ created: [], skipped: 0 });
    renderPage();
    expect(await screen.findByText('No projects in this scenario yet')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    const buttons = screen.getAllByRole('button', { name: 'Import projects' });
    fireEvent.click(buttons[buttons.length - 1]!);
    await waitFor(() => expect(api.importProjects).toHaveBeenCalledWith('plan1', 'sc1'));
  });

  it('shows what a suggestion would change and applies it only on confirmation', async () => {
    api.autofund.mockResolvedValue({
      items: [{ id: 'it1', status: 'funded', confidence: 0.9, reason: 'fits the envelope in every year', changed: true }],
      findings: [],
    });
    api.applyStatuses.mockResolvedValue([{ ...ITEM, status: 'funded' }]);
    renderPage();
    await screen.findByTestId('gap-2030');
    fireEvent.click(screen.getByRole('button', { name: /Suggest funding/ }));

    const panel = await screen.findByTestId('suggestion');
    expect(panel.textContent).toContain('Road resurfacing');
    expect(panel.textContent).toContain('Proposed -> Funded');
    expect(panel.textContent).toContain('90%');
    expect(api.applyStatuses).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(api.applyStatuses).toHaveBeenCalledWith('sc1', [{ id: 'it1', status: 'funded' }]));
  });

  it('asks for a first plan when none exists', async () => {
    api.listPlans.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText('No capital plan yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create plan' })).toBeDisabled();
  });
});
