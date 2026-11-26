// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Tests for the cost-type grid and the budget line picker: the layout keeps the
// figures exact and reconciled, every figure carries its source, empty states
// say what to add, and a read-only user sees the picker disabled with a reason.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import type { CostTypeGrid, CostTypeGridRow, CostTypeGridTotals } from './costTypeGridApi';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string } & Record<string, unknown>) => {
      if (typeof opts === 'object' && opts && 'defaultValue' in opts) {
        let dv = opts.defaultValue ?? '';
        for (const [k, v] of Object.entries(opts)) {
          if (k === 'defaultValue') continue;
          dv = dv.replaceAll(`{{${k}}}`, String(v));
        }
        return dv;
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const apiMocks = vi.hoisted(() => ({ fetchCostTypeGrid: vi.fn() }));
vi.mock('./costTypeGridApi', async (orig) => ({
  ...(await orig<typeof import('./costTypeGridApi')>()),
  fetchCostTypeGrid: apiMocks.fetchCostTypeGrid,
}));

import { CostTypeGridPanel, buildView, sumRows, UNCLASSIFIED } from './CostTypeGridPanel';
import { BudgetLinePicker } from './BudgetLinePicker';

const TYPES = ['labor', 'material', 'equipment', 'subcontractor', 'other'];

function row(code: string, category: string, budget: string, extra: Partial<CostTypeGridRow> = {}): CostTypeGridRow {
  return {
    line_id: `${code}-${category}`,
    cost_code: code,
    cost_code_title: code === '1.01' ? 'Mobilization' : '',
    cost_type: TYPES.includes(category) ? category : null,
    category,
    description: `${code} ${category}`,
    currency: 'USD',
    budget,
    committed: '0',
    actual: '0',
    forecast: budget,
    eac: budget,
    variance: '0',
    eac_basis: 'forecast',
    committed_from_documents: false,
    split_basis: null,
    editable: true,
    ...extra,
  };
}

function totals(rows: CostTypeGridRow[]): CostTypeGridTotals {
  return sumRows(rows);
}

function grid(rows: CostTypeGridRow[]): CostTypeGrid {
  const codes = [...new Set(rows.map((r) => r.cost_code))];
  return {
    project_id: 'p1',
    currency: 'USD',
    cost_types: TYPES,
    groups: codes.map((code) => {
      const own = rows.filter((r) => r.cost_code === code);
      return { cost_code: code, cost_code_title: own[0]?.cost_code_title ?? '', rows: own, subtotal: totals(own) };
    }),
    by_type: [],
    total: totals(rows),
    line_count: rows.length,
    findings: [],
  };
}

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  apiMocks.fetchCostTypeGrid.mockReset();
});

describe('buildView', () => {
  it('puts each line in its type column and adds an unclassified column only when needed', () => {
    const rows = [row('1.01', 'labor', '400.10'), row('1.01', 'labor', '0.20'), row('1.01', 'material', '200')];
    const view = buildView(grid(rows));
    expect(view.columns).toEqual(TYPES);
    const first = view.groups[0];
    expect(first?.byColumn.labor).toHaveLength(2);
    // Two lines in one cell add up exactly, not as floats.
    expect(sumRows(first?.byColumn.labor ?? []).budget).toBe('400.30');

    const withLegacy = buildView(grid([...rows, row('2.01', 'overhead', '50')]));
    expect(withLegacy.columns).toEqual([...TYPES, UNCLASSIFIED]);
    expect(withLegacy.columnTotals[UNCLASSIFIED]?.budget).toBe('50');
  });

  it('column totals add up to the grid total', () => {
    const rows = [row('1.01', 'labor', '0.10'), row('1.02', 'labor', '0.20'), row('1.02', 'other', '0.30')];
    const g = grid(rows);
    const view = buildView(g);
    const sum = ['labor', 'other'].map((c) => view.columnTotals[c]?.budget);
    expect(sum).toEqual(['0.30', '0.30']);
    expect(g.total.budget).toBe('0.60');
  });
});

describe('<CostTypeGridPanel>', () => {
  it('renders the rows, the total row and the source of a committed figure', async () => {
    apiMocks.fetchCostTypeGrid.mockResolvedValue(
      grid([
        row('1.01', 'material', '200', { committed: '250', eac: '250', eac_basis: 'committed', committed_from_documents: true }),
        row('1.01', 'labor', '400'),
      ]),
    );
    wrap(<CostTypeGridPanel projectId="p1" />);

    await waitFor(() => expect(screen.getByTestId('cost-type-grid')).toBeTruthy());
    expect(screen.getByText('Mobilization')).toBeTruthy();
    expect(screen.getAllByText('Total').length).toBeGreaterThan(0);

    const docCells = Array.from(document.querySelectorAll('td[title]')).filter((td) =>
      (td.getAttribute('title') ?? '').includes('Purchase orders and subcontracts booked to this budget line'),
    );
    expect(docCells.length).toBe(1);
    const eacCells = Array.from(document.querySelectorAll('td[title]')).filter((td) =>
      (td.getAttribute('title') ?? '').includes('Here: Committed'),
    );
    expect(eacCells.length).toBeGreaterThan(0);
  });

  it('says what to add when there are no budget lines', async () => {
    apiMocks.fetchCostTypeGrid.mockResolvedValue({ ...grid([row('1.01', 'labor', '1')]), groups: [], line_count: 0 });
    wrap(<CostTypeGridPanel projectId="p1" />);
    await waitFor(() => expect(screen.getByText('No budget lines to split yet')).toBeTruthy());
    expect(screen.getByText(/Generate a budget from your BOQ/)).toBeTruthy();
  });

  it('shows an error line when the grid cannot load', async () => {
    apiMocks.fetchCostTypeGrid.mockRejectedValue(new Error('boom'));
    wrap(<CostTypeGridPanel projectId="p1" />);
    await waitFor(() => expect(screen.getByText('Could not load the cost type grid')).toBeTruthy());
  });
});

describe('<BudgetLinePicker>', () => {
  it('lists the budget lines by cost code and type and reports the choice', async () => {
    apiMocks.fetchCostTypeGrid.mockResolvedValue(grid([row('1.01', 'material', '200'), row('1.01', 'labor', '400')]));
    wrap(<BudgetLinePicker projectId="p1" value={null} onChange={() => {}} data-testid="pick" />);
    const select = (await screen.findByTestId('pick')) as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.text)).toEqual([
      'Not booked to a budget line',
      '1.01 · Material · 1.01 material',
      '1.01 · Labor · 1.01 labor',
    ]);
    expect(select.disabled).toBe(false);
  });

  it('is disabled with the reason for a read-only user', async () => {
    apiMocks.fetchCostTypeGrid.mockResolvedValue(grid([row('1.01', 'material', '200')]));
    wrap(
      <BudgetLinePicker
        projectId="p1"
        value="1.01-material"
        onChange={() => {}}
        disabled
        disabledReason="Your role can read budget lines but not change this link."
        data-testid="pick"
      />,
    );
    const select = (await screen.findByTestId('pick')) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    expect(select.title).toBe('Your role can read budget lines but not change this link.');
    expect(screen.getByText('Your role can read budget lines but not change this link.')).toBeTruthy();
  });

  it('renders nothing while the project has no budget lines and no saved link', async () => {
    apiMocks.fetchCostTypeGrid.mockResolvedValue({ ...grid([row('1.01', 'labor', '1')]), groups: [] });
    wrap(<BudgetLinePicker projectId="p1" value={null} onChange={() => {}} data-testid="pick" />);
    await waitFor(() => expect(apiMocks.fetchCostTypeGrid).toHaveBeenCalled());
    expect(screen.queryByTestId('pick')).toBeNull();
  });
});
