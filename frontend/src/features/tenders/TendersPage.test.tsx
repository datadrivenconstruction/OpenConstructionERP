// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { TendersPage } from './TendersPage';
import { tenderEditPath, type TenderSummary } from './api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

import { apiGet } from '@/shared/lib/api';

const mockGet = vi.mocked(apiGet);
const PROJECT_ID = '11111111-1111-1111-1111-111111111111';

function row(over: Partial<TenderSummary>): TenderSummary {
  return {
    id: crypto.randomUUID(),
    project_id: PROJECT_ID,
    code: 'BP-001',
    title: 'Drywall',
    status: 'open',
    kind: 'subcontract',
    source: 'native',
    source_id: null,
    currency: 'EUR',
    submission_deadline: null,
    bid_count: 2,
    lowest_total: '148200.00',
    awarded_amount: null,
    awarded_bidder: null,
    ...over,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TendersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TendersPage', () => {
  beforeEach(() => {
    mockGet.mockReset();
    useProjectContextStore.setState({ activeProjectId: PROJECT_ID, activeProjectName: 'Riverside' });
  });

  it('lists native packages and copies of old tenders and RFQs together', async () => {
    mockGet.mockResolvedValue([
      row({ code: 'BP-001' }),
      row({ code: 'TND-0001', source: 'tendering', status: 'awarded', awarded_bidder: 'Nord' }),
      row({ code: 'RFQ-7', source: 'rfq_bidding', kind: 'supply', bid_count: 1 }),
    ]);
    renderPage();
    expect(await screen.findByText('TND-0001')).toBeInTheDocument();
    expect(screen.getByText('RFQ-7').closest('a')).toHaveAttribute('href', `/projects/${PROJECT_ID}/rfq-bidding`);
    expect(screen.getByText('Nord')).toBeInTheDocument();
    expect(mockGet.mock.calls[0]![0]).toContain(`project_id=${PROJECT_ID}`);
  });

  it('asks the server for one kind when a kind tab is chosen', async () => {
    mockGet.mockResolvedValue([]);
    renderPage();
    await screen.findByText('No tenders in this project yet.');
    await userEvent.click(screen.getByRole('tab', { name: 'Supply' }));
    await waitFor(() => expect(mockGet.mock.calls.some(([url]) => String(url).includes('kind=supply'))).toBe(true));
  });

  it('sends each source to the page that still edits it', () => {
    expect(tenderEditPath({ source: 'tendering', project_id: 'p' })).toBe('/tendering');
    expect(tenderEditPath({ source: 'native', project_id: 'p' })).toBe('/projects/p/bid-management');
  });
});
