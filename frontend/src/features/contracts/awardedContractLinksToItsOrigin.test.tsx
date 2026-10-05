// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A contract drafted by an award carries where it came from on its metadata:
// the tender package, the bid package and the bill the scope was priced in.
// The drawer's Related strip linked only to the counterparty and to the
// variations register, so the reader could not walk back from the contract to
// the tender that produced it. What is pinned: each origin id becomes a link
// to the record, and a contract written by hand draws none of them.
//
// The harness is the one highlightOpensTheContract.test.tsx uses.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const setSearchParamsSpy = vi.fn();
/** The query string the page mounts with; each test sets it before rendering. */
let search = '';

// The shared setup stubs useSearchParams to a permanently empty set. The
// factory registered last wins, so this one replaces it for this file only.
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
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

import { ContractsPage } from './ContractsPage';
import type { ContractItem } from './api';

const CONTRACT: ContractItem = {
  id: 'ct-1',
  code: 'MC-01',
  title: 'Main works',
  contract_type: 'lump_sum',
  counterparty_type: 'client',
  counterparty_id: null,
  project_id: 'p-1',
  parent_contract_id: null,
  start_date: '2026-01-01',
  end_date: '2026-12-31',
  total_value: '1000000.00',
  original_contract_value: '1000000.00',
  currency: 'EUR',
  retention_percent: '5',
  retention_release_event: 'substantial_completion',
  status: 'active',
  signed_at: '2026-01-01T09:00:00Z',
  template_code: null,
  template_version: null,
  terms: {},
  created_by: null,
  metadata: {} as Record<string, unknown>,
  created_at: '2026-01-01T09:00:00Z',
  updated_at: '2026-01-01T09:00:00Z',
};

const PROJECT = { id: 'p-1', name: 'Riverside', currency: 'EUR' };

/** An analytics endpoint's response for a contract that has nothing recorded
 *  yet. Each of these is an object, not a list, and the panels read into it
 *  without guarding — rightly, because the API always sends the whole shape.
 *  A route that answered them with `[]` would not be an empty fixture, it
 *  would be a fixture of the wrong type, and the panel would throw during
 *  render and take the drawer down with it. */
const EMPTY_ANALYTICS: Record<string, unknown> = {
  'sov-status': {
    by_line: {},
    totals: { scheduled: 0, billed: 0, earned: 0, paid: 0, retained: 0, percent_complete: 0 },
  },
  completeness: {
    contract_id: 'ct-1',
    status: 'passed',
    score: 1,
    summary: {
      status: 'passed',
      score: 1,
      counts: { total: 0, passed: 0, errors: 0, warnings: 0, infos: 0, engine_errors: 0 },
    },
    errors: [],
    warnings: [],
  },
  'eot-summary': {
    contract_id: 'ct-1',
    claims_count: 0,
    pending_count: 0,
    decided_count: 0,
    total_days_claimed: 0,
    total_days_granted: 0,
    latest_revised_completion_date: null,
  },
  'final-account-checklist': {
    contract_id: 'ct-1',
    ready: false,
    completion_percent: 0,
    passed_count: 0,
    applicable_count: 0,
    total_count: 0,
    items: [],
  },
  'security-coverage': {
    contract_id: 'ct-1',
    currency: 'EUR',
    count: 0,
    active_count: 0,
    total_active_amount: 0,
    by_status: {},
    active_types: [],
  },
  'payment-plan': {
    contract_id: 'ct-1',
    currency: 'EUR',
    contract_total: 0,
    scheduled_total: 0,
    percent_scheduled: null,
    default_payment_terms_days: null,
    lines: [],
    findings: [],
  },
  'milestone-schedule': {
    contract_id: 'ct-1',
    currency: 'EUR',
    count: 0,
    scheduled_value: 0,
    milestones: [],
  },
};

/** Routes a GET by path. The panels the drawer opens beside itself own their
 *  own data and none of this question, so each is answered with the empty
 *  form of its own response — a shape-blind default answers a question it was
 *  not asked. The two that stay refused have error states of their own and
 *  no bearing on which record the drawer opens. */
let metadata: Record<string, unknown> = {};

function routeGet(): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/projects/')) return Promise.resolve([PROJECT]);
    if (path.startsWith('/v1/contracts/contracts/?')) {
      return Promise.resolve({ items: [{ ...CONTRACT, metadata }], total: 1, offset: 0, limit: 200 });
    }
    if (path.includes('/dashboard') || path.includes('retention')) {
      return Promise.reject(new Error(`not served in this test: ${path}`));
    }
    const analytics = Object.keys(EMPTY_ANALYTICS).find((suffix) => path.endsWith(`/${suffix}`));
    if (analytics) return Promise.resolve(EMPTY_ANALYTICS[analytics]);
    if (path.includes('?')) return Promise.resolve({ items: [], total: 0, offset: 0, limit: 200 });
    // What is left really is a list on the wire: /lines, /parties,
    // /securities and the template catalogue.
    return Promise.resolve([]);
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/contracts${search}`]}>
        <ContractsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setSearchParamsSpy.mockClear();
  api.apiGet.mockReset();
  metadata = {};
  search = '?highlight=ct-1';
  routeGet();
});

afterEach(() => cleanup());

describe('a contract drafted by an award links to where it came from', () => {
  it('links to the tender package, the bid package and the source bill', async () => {
    metadata = {
      source: 'bid_management.package.awarded',
      tender_package_id: 'tp-1',
      bid_package_id: 'bp-1',
      boq_id: 'boq-7',
    };
    renderPage();

    const dialog = within(await screen.findByRole('dialog'));
    expect((await dialog.findByRole('link', { name: /From tender/ })).getAttribute('href')).toBe(
      '/tendering?package=tp-1',
    );
    expect(dialog.getByRole('link', { name: /From bid package/ }).getAttribute('href')).toBe(
      '/bid-management?highlight=bp-1',
    );
    expect(dialog.getByRole('link', { name: /Source BOQ/ }).getAttribute('href')).toBe('/boq/boq-7');
  });

  it('draws only the origins the contract carries', async () => {
    // The tender path writes boq_id: null for a package with no bill.
    metadata = { source: 'tendering.package.awarded', tender_package_id: 'tp-1', boq_id: null };
    renderPage();

    const dialog = within(await screen.findByRole('dialog'));
    await dialog.findByRole('link', { name: /From tender/ });
    expect(dialog.queryByRole('link', { name: /From bid package/ })).toBeNull();
    expect(dialog.queryByRole('link', { name: /Source BOQ/ })).toBeNull();
  });

  it('draws no origin link on a contract written by hand', async () => {
    renderPage();

    const dialog = within(await screen.findByRole('dialog'));
    // The variations chip is in the same strip, so its presence proves the
    // strip rendered and the absence below is not a render that never came.
    await dialog.findByRole('link', { name: /Variations on this contract/ });
    expect(dialog.queryByRole('link', { name: /From tender/ })).toBeNull();
    expect(dialog.queryByRole('link', { name: /From bid package/ })).toBeNull();
    expect(dialog.queryByRole('link', { name: /Source BOQ/ })).toBeNull();
  });
});
