// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The page keeps its tab in the address, so a link and the back button land on
// the tab a person was reading, and it asks before a gate, a zone or a
// delivery is deleted.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';

vi.mock('react-i18next', async () => (await import('./i18nMock')).i18nMockModule);
vi.mock('@/shared/hooks/useActiveProjectId', () => ({ useActiveProjectId: () => 'p1' }));
vi.mock('@/shared/lib/projectList', () => ({ fetchProjectList: vi.fn(async () => [{ id: 'p1', name: 'Harbour' }]) }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    fetchGates: vi.fn(),
    fetchLaydownZones: vi.fn(),
    fetchDeliveries: vi.fn(),
    fetchSiteLogisticsStats: vi.fn(),
    fetchBoardCan: vi.fn(),
    deleteGate: vi.fn(),
  };
});

import * as api from '../../api';
import { SiteLogisticsPage } from '../../SiteLogisticsPage';

const mocked = vi.mocked(api);
const yes = { allowed: true, applies: true, reason: null };

function Where() {
  const { search } = useLocation();
  return <span data-testid="where">{search}</span>;
}

function renderPage(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <SiteLogisticsPage />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.fetchGates.mockResolvedValue([
    {
      id: 'g1',
      can: { delete: yes },
      project_id: 'p1',
      name: 'North gate',
      open_time: '06:00',
      close_time: '18:00',
      capacity_per_slot: 2,
      notes: null,
      created_by: null,
      metadata: {},
      created_at: '2026-03-01T08:00:00Z',
      updated_at: '2026-03-01T08:00:00Z',
    },
  ]);
  mocked.fetchLaydownZones.mockResolvedValue([]);
  mocked.fetchDeliveries.mockResolvedValue([]);
  mocked.fetchSiteLogisticsStats.mockResolvedValue({
    total_deliveries: 0,
    gate_count: 1,
    zone_count: 0,
  } as unknown as Awaited<ReturnType<typeof api.fetchSiteLogisticsStats>>);
  mocked.fetchBoardCan.mockResolvedValue({});
  mocked.deleteGate.mockResolvedValue(undefined);
});
afterEach(cleanup);

describe('site logistics page', () => {
  it('opens the tab named in the address', async () => {
    renderPage('/site-logistics?tab=gates');
    expect(await screen.findByText('North gate')).toBeInTheDocument();
  });

  it('writes the tab into the address when a tab is chosen, and leaves the default tab bare', async () => {
    renderPage('/site-logistics');
    expect(screen.getByTestId('where').textContent).toBe('');
    fireEvent.click(await screen.findByTestId('site-logistics-tab-gates'));
    expect(screen.getByTestId('where').textContent).toBe('?tab=gates');
    fireEvent.click(screen.getByTestId('site-logistics-tab-deliveries'));
    expect(screen.getByTestId('where').textContent).toBe('');
  });

  it('falls back to the delivery board for a tab it does not know', async () => {
    renderPage('/site-logistics?tab=nonsense');
    expect(await screen.findByTestId('site-logistics-tab-deliveries')).toBeInTheDocument();
    expect(screen.queryByText('North gate')).toBeNull();
  });

  it('asks before a gate is deleted and deletes nothing until confirmed', async () => {
    renderPage('/site-logistics?tab=gates');
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Delete this gate?');
    expect(mocked.deleteGate).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(mocked.deleteGate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(mocked.deleteGate).toHaveBeenCalledWith('g1'));
  });
});
