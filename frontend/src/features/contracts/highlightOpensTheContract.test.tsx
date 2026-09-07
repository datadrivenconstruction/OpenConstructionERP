// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issue #435, the navigation half, as the contract register consumes it. A
// variation order's "Contract" pill and a change order's "Applies to
// contract" pill land here as /contracts?highlight=<id>. Until now this page
// read only ?counterparty=, so both pills had to send the reader to the bare
// register, and the variations drawer test pinned that as the honest
// destination. This file is the other half of that pin: the register opens
// on the contract, and closing the drawer takes the param back out.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
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
  currency: 'EUR',
  retention_percent: '5',
  retention_release_event: 'practical_completion',
  status: 'active',
  signed_at: '2026-01-01T09:00:00Z',
  template_code: null,
  template_version: null,
  terms: {},
  created_by: null,
  metadata: {},
  created_at: '2026-01-01T09:00:00Z',
  updated_at: '2026-01-01T09:00:00Z',
};

const PROJECT = { id: 'p-1', name: 'Riverside', currency: 'EUR' };

/** Routes a GET by path. The panels the drawer opens beside itself own their
 *  own data and none of this question; the two that cannot take an empty
 *  list are refused outright, which their own error states absorb. */
function routeGet(): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/projects/')) return Promise.resolve([PROJECT]);
    if (path.startsWith('/v1/contracts/contracts/?')) {
      return Promise.resolve({ items: [CONTRACT], total: 1, offset: 0, limit: 200 });
    }
    if (path.includes('/dashboard') || path.includes('retention')) {
      return Promise.reject(new Error(`not served in this test: ${path}`));
    }
    if (path.includes('?')) return Promise.resolve({ items: [], total: 0, offset: 0, limit: 200 });
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
  routeGet();
});

afterEach(() => cleanup());

describe('a deep link into the contract register', () => {
  it('opens the drawer of the contract the link names', async () => {
    search = '?highlight=ct-1';
    renderPage();

    const dialog = await screen.findByRole('dialog');
    expect(dialog.getAttribute('aria-labelledby')).toBe('contract-drawer-title');
    expect(screen.getByText('MC-01 — Main works')).toBeTruthy();
  });

  it('takes the highlight out of the URL when the drawer is closed', async () => {
    search = '?highlight=ct-1';
    renderPage();

    await screen.findByRole('dialog');
    fireEvent.click(screen.getByLabelText('Close'));

    expect(setSearchParamsSpy).toHaveBeenCalledTimes(1);
    const [updater, options] = setSearchParamsSpy.mock.calls[0] as [
      (prev: URLSearchParams) => URLSearchParams,
      { replace?: boolean },
    ];
    expect(options).toEqual({ replace: true });
    expect(updater(new URLSearchParams(search)).get('highlight')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens nothing without a highlight', async () => {
    // The control: a register that opened its first contract on mount would
    // pass the test above for the wrong reason.
    search = '';
    renderPage();

    await waitFor(() =>
      expect(api.apiGet).toHaveBeenCalledWith(expect.stringContaining('/v1/contracts/contracts/?')),
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
