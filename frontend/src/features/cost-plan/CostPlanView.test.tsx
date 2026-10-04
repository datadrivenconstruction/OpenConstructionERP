// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Tests for <CostPlanView>.
//
// The screen formats what the server computed and must never drop a row the
// server returned: element names come from the plan (data), unallocated money
// is shown with its count, the markup cascade keeps the server's order, a typed
// floor area is sent to the server and a bad one is refused before it is, and
// the export goes out with the area the reader is looking at. A reopened plan
// is read again, never served from the app's two-minute query cache.

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

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

const apiMocks = vi.hoisted(() => ({
  nrm1: vi.fn(),
  exportNrm1Xlsx: vi.fn(),
}));
vi.mock('./api', () => ({
  costPlanApi: {
    nrm1: apiMocks.nrm1,
    exportNrm1Xlsx: apiMocks.exportNrm1Xlsx,
  },
}));

import { CostPlanView } from './CostPlanView';
import type { Nrm1CostPlan } from './api';

const sub = (total: string, cost_per_m2: string | null, share_pct: string | null) => ({
  total,
  cost_per_m2,
  share_pct,
});

function makePlan(overrides: Partial<Nrm1CostPlan> = {}): Nrm1CostPlan {
  return {
    standard: 'NRM1',
    boq_id: 'boq-1',
    boq_name: 'Stage 2',
    project_id: 'p-1',
    currency: 'GBP',
    gifa: '1000',
    gifa_source: 'project',
    groups: [
      {
        code: '1',
        name: 'Substructure',
        kind: 'works',
        position_count: 1,
        ...sub('1000', '1.00', '50.00'),
        elements: [{ code: '1.1', name: 'Substructure', position_count: 1, ...sub('1000', '1.00', '50.00') }],
        group_level: null,
      },
      {
        code: '2',
        name: 'Superstructure',
        kind: 'works',
        position_count: 2,
        ...sub('400', '0.40', '20.00'),
        elements: [
          { code: '2.1', name: 'Frame', position_count: 0, ...sub('0', '0.00', '0.00') },
          { code: '2.5', name: 'External walls', position_count: 1, ...sub('370', '0.37', '18.50') },
        ],
        group_level: { position_count: 1, codes: ['2'], ...sub('30', '0.03', '1.50') },
      },
    ],
    works_estimate: sub('1400', '1.40', '70.00'),
    addon_groups: [
      {
        code: '9',
        name: "Main contractor's preliminaries",
        kind: 'addon',
        position_count: 1,
        ...sub('100', '0.10', '5.00'),
        elements: [],
        group_level: { position_count: 1, codes: ['9'], ...sub('100', '0.10', '5.00') },
      },
      {
        code: '13',
        name: 'Risks',
        kind: 'addon',
        position_count: 0,
        ...sub('0', '0.00', '0.00'),
        elements: [],
        group_level: null,
      },
    ],
    unallocated: {
      position_count: 1,
      positions: [
        { id: 'pos-9', ordinal: '06.001', description: 'Uncoded item', code: 'abc', reason: 'invalid_code', total: '20' },
      ],
      positions_truncated: false,
      ...sub('20', '0.02', '1.00'),
    },
    direct_cost: sub('1520', '1.52', '76.00'),
    markups: [
      {
        id: 'm-1',
        name: 'Preliminaries line',
        category: 'overhead',
        markup_type: 'percentage',
        apply_to: 'direct_cost',
        percentage: '13',
        fixed_amount: null,
        base: '1520',
        running_total: '1717.60',
        scoped: false,
        ...sub('197.60', '0.20', '9.88'),
      },
      {
        id: 'm-2',
        name: 'Overheads and profit',
        category: 'profit',
        markup_type: 'percentage',
        apply_to: 'cumulative',
        percentage: '10',
        fixed_amount: null,
        base: '1717.60',
        running_total: '1889.36',
        scoped: false,
        ...sub('171.76', '0.17', '8.59'),
      },
    ],
    markups_total: sub('369.36', '0.37', '18.47'),
    grand_total: sub('1889.36', '1.89', '100.00'),
    position_count: 5,
    allocated_count: 4,
    inherited_count: 1,
    warnings: ['unallocated_positions', 'addons_in_bill_and_markups'],
    ...overrides,
  };
}

function renderView(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={client}>
      <CostPlanView boqId="boq-1" />
    </QueryClientProvider>,
  );
}

/** A client with the app's own defaults from main.tsx, where caching bites. */
function appLikeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 120_000, gcTime: 5 * 60_000, refetchOnWindowFocus: false } },
  });
}

beforeEach(() => {
  apiMocks.nrm1.mockResolvedValue(makePlan());
  apiMocks.exportNrm1Xlsx.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('CostPlanView', () => {
  it('renders the elemental structure from the plan, with group-level and unallocated money shown', async () => {
    renderView();
    const table = await screen.findByTestId('cost-plan-table');
    expect(apiMocks.nrm1).toHaveBeenCalledWith('boq-1', null);

    expect(within(screen.getByTestId('cost-plan-element-2.5')).getByText('External walls')).toBeTruthy();
    expect(within(screen.getByTestId('cost-plan-group-level-2')).getByText('Group level, no element given')).toBeTruthy();
    // An element with no cost is hidden until asked for.
    expect(screen.queryByTestId('cost-plan-element-2.1')).toBeNull();
    // A priced add-on group is shown; an unpriced one is not.
    expect(screen.getByTestId('cost-plan-group-9')).toBeTruthy();
    expect(screen.queryByTestId('cost-plan-group-13')).toBeNull();

    const unallocated = screen.getByTestId('cost-plan-unallocated');
    expect(within(unallocated).getByText('Not allocated to an element')).toBeTruthy();
    expect(within(unallocated).getByText('1')).toBeTruthy();
    expect(within(screen.getByTestId('cost-plan-unallocated-list')).getByText('Code is not an NRM number')).toBeTruthy();

    expect(table.textContent).toContain('Building works estimate');
    expect(screen.getByTestId('cost-plan-warnings').textContent).toContain('counted twice');
  });

  it('reads the plan again when it is reopened, even inside the app-wide cache window', async () => {
    const client = appLikeClient();
    const first = renderView(client);
    await screen.findByTestId('cost-plan-table');
    expect(screen.getByText('Uncoded item')).toBeTruthy();
    first.unmount();
    // The estimator closes the dialog and codes the position in the grid.
    await new Promise((resolve) => setTimeout(resolve, 0));

    apiMocks.nrm1.mockResolvedValue(
      makePlan({
        unallocated: { position_count: 0, positions: [], positions_truncated: false, ...sub('0', '0.00', '0.00') },
        allocated_count: 5,
        warnings: ['addons_in_bill_and_markups'],
      }),
    );
    renderView(client);
    // No stale figures while the fresh plan is on its way.
    expect(screen.queryByText('Uncoded item')).toBeNull();
    await waitFor(() => expect(screen.getByText('5 / 5')).toBeTruthy());
    expect(apiMocks.nrm1).toHaveBeenCalledTimes(2);
    expect(screen.queryByText('Uncoded item')).toBeNull();
  });

  it('keeps the markup cascade in the order the server returned and says what each line was based on', async () => {
    renderView();
    const first = await screen.findByTestId('cost-plan-markup-0');
    const second = screen.getByTestId('cost-plan-markup-1');
    expect(first.textContent).toContain('Preliminaries line');
    expect(first.textContent).toContain('13% on direct cost');
    expect(second.textContent).toContain('Overheads and profit');
    expect(second.textContent).toContain('10% on running subtotal');
    expect(screen.getByTestId('cost-plan-grand-total').textContent).toContain('100');
  });

  it('shows elements with no cost on request', async () => {
    renderView();
    await screen.findByTestId('cost-plan-table');
    fireEvent.click(screen.getByLabelText('Show elements with no cost'));
    expect(screen.getByTestId('cost-plan-element-2.1')).toBeTruthy();
  });

  it('sends an entered floor area to the server and refuses a non-positive one', async () => {
    renderView();
    await screen.findByTestId('cost-plan-table');
    const input = screen.getByLabelText('GIFA (m2)');

    fireEvent.change(input, { target: { value: '0' } });
    fireEvent.click(screen.getByText('Apply'));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(apiMocks.nrm1).toHaveBeenCalledTimes(1);

    apiMocks.nrm1.mockResolvedValue(makePlan({ gifa: '2400', gifa_source: 'entered' }));
    fireEvent.change(input, { target: { value: '2400' } });
    fireEvent.click(screen.getByText('Apply'));
    await waitFor(() => expect(apiMocks.nrm1).toHaveBeenLastCalledWith('boq-1', '2400'));
    // Export stays disabled until the plan for the new area has arrived.
    expect(await screen.findByText(/entered here/)).toBeTruthy();

    fireEvent.click(screen.getByText('Export to Excel'));
    await waitFor(() => expect(apiMocks.exportNrm1Xlsx).toHaveBeenCalledWith('boq-1', '2400'));
  });

  it('shows the cost per m2 as absent, not zero, when no floor area is known', async () => {
    apiMocks.nrm1.mockResolvedValue(
      makePlan({
        gifa: null,
        gifa_source: 'none',
        grand_total: sub('1889.36', null, '100.00'),
        warnings: ['no_gifa'],
      }),
    );
    renderView();
    const total = await screen.findByTestId('cost-plan-grand-total');
    const cells = total.querySelectorAll('td');
    expect(cells[4]?.textContent).toBe('-');
    expect(screen.getByTestId('cost-plan-warnings').textContent).toContain('No gross internal floor area');
  });
});
