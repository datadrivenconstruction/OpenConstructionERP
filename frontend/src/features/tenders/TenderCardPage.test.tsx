// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { TenderCardPage } from './TenderCardPage';
import { LegacyTenderRedirect } from './LegacyTenderRedirect';
import type { TenderDetail } from './api';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

import { apiGet } from '@/shared/lib/api';

const mockGet = vi.mocked(apiGet);

const DETAIL: TenderDetail = {
  package: {
    id: 'pkg-1',
    project_id: 'proj-1',
    code: 'TND-0001',
    title: 'Drywall',
    status: 'closed',
    package_type: 'subcontract',
    currency: 'EUR',
    submission_deadline: null,
  },
  source: 'tendering',
  source_id: 'old-1',
  read_only: true,
  line_items: [{ id: 'l1', code: '01', description: 'Partition 100 mm', unit: 'm2', quantity: '5200', order_index: 0 }],
  invitations: [],
  bidders: [
    { id: 'b1', company_name: 'Trockenbau Nord', contact_email: 'n@x.test', status: 'active' },
    { id: 'b2', company_name: 'Ausbau Sued', contact_email: 's@x.test', status: 'active' },
  ],
  submissions: [
    { id: 's2', bidder_id: 'b2', submitted_at: null, total_amount: '151999.99', currency: 'EUR', validity_days: null, late_reason: null },
    { id: 's1', bidder_id: 'b1', submitted_at: null, total_amount: '148200.00', currency: 'EUR', validity_days: null, late_reason: null },
  ],
  award: null,
  questions: [{ id: 'q1', question: 'Fire rating?', answer: 'EI 30', asked_at: null, answered_at: null }],
  comparison: null,
};

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/tenders/:tenderId" element={<><TenderCardPage /><Where /></>} />
          <Route path="/tenders" element={<Where />} />
          <Route path="/tenders/edit/tendering" element={<Where />} />
          <Route path="/tendering" element={<LegacyTenderRedirect source="tendering" />} />
          <Route path="/rfq-bidding" element={<LegacyTenderRedirect source="rfq_bidding" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TenderCardPage', () => {
  beforeEach(() => mockGet.mockReset());

  it('shows every tab of a copied tender, cheapest bid first', async () => {
    mockGet.mockResolvedValue(DETAIL);
    renderAt('/tenders/pkg-1');
    expect(await screen.findByText('Partition 100 mm')).toBeInTheDocument();
    expect(screen.getByText(/older module/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: /Bids/ }));
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('Trockenbau Nord');
    await userEvent.click(screen.getByRole('tab', { name: /Q&A/ }));
    expect(screen.getByText('EI 30')).toBeInTheDocument();
  });

  it('edits a copy in the editor of the module it came from', async () => {
    mockGet.mockResolvedValue(DETAIL);
    renderAt('/tenders/pkg-1');
    await userEvent.click(await screen.findByRole('button', { name: /Edit/ }));
    expect(screen.getByTestId('where')).toHaveTextContent('/tenders/edit/tendering?package=old-1');
  });
});

describe('LegacyTenderRedirect', () => {
  beforeEach(() => mockGet.mockReset());

  it('opens the card of the package an old link named', async () => {
    mockGet.mockResolvedValueOnce({ package_id: 'pkg-1', source: 'tendering' }).mockResolvedValue(DETAIL);
    renderAt('/tendering?package=old-1');
    expect(await screen.findByText('Partition 100 mm')).toBeInTheDocument();
    expect(String(mockGet.mock.calls[0]![0])).toContain('source_table=oe_tendering_package&source_id=old-1');
  });

  it('sends a plain old address to the list filtered by origin', async () => {
    renderAt('/rfq-bidding');
    expect(await screen.findByTestId('where')).toHaveTextContent('/tenders?source=rfq_bidding');
  });
});
