// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issue #435, the navigation half, as the variations workspace consumes it. A
// change order's "From variation" pill and a management-of-change entry's
// "Linked variation" pill land here as /variations?tab=<kind>&highlight=<id>.
// Before this the page had no reader for either param, so every link into it
// opened the notices list and left the reader to find the record by hand,
// which is the shape the issue calls out as fragmented navigation.
//
// The assertions are about what the URL does to the page, not about the
// pills that write the URL (those have their own tests): the tab the page
// opens on, the drawer it opens, where the drawer's own pills go from there,
// and that closing the drawer takes the highlight back out of the URL so a
// remount does not re-open a record the user just closed.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const navigateSpy = vi.fn();
const setSearchParamsSpy = vi.fn();
/** The query string the page mounts with; each test sets it before rendering. */
let search = '';

// The shared setup stubs useSearchParams to a permanently empty set, which is
// right for pages that only write to it and wrong here. The factory registered
// last wins, so this one replaces it for this file only.
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(search), setSearchParamsSpy],
  };
});

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => 'p-1',
}));

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), insights: [], kpis: [], series: [] }),
}));

import { VariationsPage } from './VariationsPage';
import type { VariationOrder } from './api';

const ORDER: VariationOrder = {
  id: 'vo-1',
  project_id: 'p-1',
  variation_request_id: null,
  code: 'VO-001',
  title: 'Extra piling to grid F',
  final_cost_impact: '12500.00',
  final_schedule_days: 4,
  currency: 'EUR',
  agreed_at: null,
  signed_by: null,
  status: 'issued',
  reference_change_order_id: 'co-42',
  affected_contract_id: 'ct-7',
  implementation_started_at: null,
  implementation_completed_at: null,
  metadata: {},
  created_at: '2026-03-01T09:00:00Z',
  updated_at: '2026-03-01T09:00:00Z',
};

const PROJECT = { id: 'p-1', name: 'Riverside', currency: 'EUR' };

const DASHBOARD = {
  notices_open: 0,
  requests_pending: 0,
  variation_orders_active: 1,
  cost_impact_total: '12500.00',
  currency: 'EUR',
  schedule_impact_days: 4,
  eot_claims_open: 0,
};

/** Routes a GET by path. Registers answer a page; everything else an empty list. */
function routeGet(): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/projects/')) return Promise.resolve([PROJECT]);
    if (path.startsWith('/v1/variations/dashboard/')) return Promise.resolve(DASHBOARD);
    if (path.startsWith('/v1/variations/variation-orders/')) {
      return Promise.resolve({ items: [ORDER], total: 1, offset: 0, limit: 200 });
    }
    if (path.includes('?')) return Promise.resolve({ items: [], total: 0, offset: 0, limit: 200 });
    return Promise.resolve([]);
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/variations${search}`]}>
        <VariationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Runs the updater a close handed to setSearchParams over the URL it closed from. */
function paramsAfterClose(): URLSearchParams {
  expect(setSearchParamsSpy).toHaveBeenCalledTimes(1);
  const [updater, options] = setSearchParamsSpy.mock.calls[0] as [
    (prev: URLSearchParams) => URLSearchParams,
    { replace?: boolean },
  ];
  expect(options).toEqual({ replace: true });
  return updater(new URLSearchParams(search));
}

beforeEach(() => {
  navigateSpy.mockClear();
  setSearchParamsSpy.mockClear();
  api.apiGet.mockReset();
  routeGet();
});

afterEach(() => cleanup());

describe('a deep link into the variations workspace', () => {
  it('opens the tab the link names and the drawer of the record it names', async () => {
    search = '?tab=orders&highlight=vo-1';
    renderPage();

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Extra piling to grid F')).toBeTruthy();
    expect(screen.getByRole('tab', { selected: true }).id).toBe('variations-tab-orders');
  });

  it('carries the drawer on to the contract the order amends', async () => {
    // The chain continues from here: the order pill on the change-order page
    // landed on this drawer, and this drawer's contract pill lands on the
    // contract, not on the contract register.
    search = '?tab=orders&highlight=vo-1';
    renderPage();

    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByText('Contract'));

    expect(navigateSpy).toHaveBeenCalledWith('/contracts?highlight=ct-7');
    expect(navigateSpy).not.toHaveBeenCalledWith('/contracts');
  });

  it('takes the highlight out of the URL when the drawer is closed, and keeps the tab', async () => {
    search = '?tab=orders&highlight=vo-1';
    renderPage();

    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByLabelText('Close'));

    const next = paramsAfterClose();
    expect(next.get('highlight')).toBeNull();
    expect(next.get('tab')).toBe('orders');
  });

  it('opens nothing without a highlight, and no drawer on a tab it does not have', async () => {
    // The control. A page that opened a drawer on any highlight, or guessed a
    // kind for an id with no tab, would pass the tests above and be wrong.
    search = '?tab=invoices&highlight=vo-1';
    renderPage();

    await waitFor(() =>
      expect(api.apiGet).toHaveBeenCalledWith(expect.stringContaining('/v1/projects/')),
    );
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('tab', { selected: true }).id).toBe('variations-tab-notices');
    expect(setSearchParamsSpy).not.toHaveBeenCalled();
  });
});
