// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The contract register keeps client contracts (income) and subcontracts (cost)
// apart: a filter, a total per side, and never one sum across both. A draft can
// be deleted from its row after a confirmation; a signed contract cannot.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within, waitFor } from '@testing-library/react';
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

const CLIENT: ContractItem = {
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
  metadata: {},
  created_at: '2026-01-01T09:00:00Z',
  updated_at: '2026-01-01T09:00:00Z',
};

const PROJECT = { id: 'p-1', name: 'Riverside', currency: 'EUR' };

const SUB: ContractItem = {
  ...CLIENT,
  id: 'ct-2',
  code: 'SC-01',
  title: 'Concrete works',
  counterparty_type: 'subcontractor',
  total_value: '250000.00',
  status: 'draft',
  signed_at: null,
};

function routeGet(): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/projects/')) return Promise.resolve([PROJECT]);
    if (path.startsWith('/v1/contracts/contracts/?')) {
      return Promise.resolve({ items: [CLIENT, SUB], total: 2, offset: 0, limit: 200 });
    }
    if (path.includes('?')) return Promise.resolve({ items: [], total: 0, offset: 0, limit: 200 });
    return Promise.resolve([]);
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/contracts']}>
        <ContractsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  search = '';
  api.apiGet.mockReset();
  api.apiDelete.mockReset();
  api.apiDelete.mockResolvedValue(undefined);
  routeGet();
});

afterEach(() => cleanup());

describe('client contracts and subcontracts', () => {
  it('shows one total per side, never one across both', async () => {
    renderPage();
    await screen.findByText('MC-01');
    const client = screen.getByTestId('contracts-total-client');
    const sub = screen.getByTestId('contracts-total-subcontractor');
    expect(client.textContent).toContain('1,000,000');
    expect(client.textContent).not.toContain('250,000');
    expect(sub.textContent).toContain('250,000');
    expect(sub.textContent).not.toContain('1,000,000');
    expect(screen.queryByText('1,250,000')).toBeNull();
  });

  it('filters the register to one side', async () => {
    renderPage();
    await screen.findByText('MC-01');
    const group = screen.getByTestId('contracts-side-filter');
    fireEvent.click(within(group).getByText(/Subcontracts/));
    expect(screen.queryByText('MC-01')).toBeNull();
    expect(screen.getByText('SC-01')).toBeTruthy();
    expect(screen.queryByTestId('contracts-total-client')).toBeNull();
  });
});

describe('deleting a contract from the register', () => {
  it('offers delete on a draft only', async () => {
    renderPage();
    await screen.findByText('MC-01');
    expect((screen.getByTestId('contract-row-delete-ct-1') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByTestId('contract-row-delete-ct-2') as HTMLButtonElement).disabled).toBe(false);
  });

  it('asks first, then deletes the draft', async () => {
    renderPage();
    await screen.findByText('SC-01');
    fireEvent.click(screen.getByTestId('contract-row-delete-ct-2'));
    expect(api.apiDelete).not.toHaveBeenCalled();
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(api.apiDelete).toHaveBeenCalledWith('/v1/contracts/contracts/ct-2'));
  });
});
