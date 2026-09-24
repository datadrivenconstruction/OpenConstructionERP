// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The RFQ page counted and filtered by `issued`, `evaluating` and `closed`,
// statuses the server's RFQ status machine never writes (it uses `published`,
// `bids_received`, `po_issued`, `completed` and `cancelled`). So the Open
// figure was always 0, no RFQ out with vendors offered Compare, and the
// status filter asked the server for values no row carries. What is pinned:
// the page counts, offers and filters by the server's own statuses.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ fetchRFQs: vi.fn() }));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchRFQs: (...args: unknown[]) => mocks.fetchRFQs(...args),
    fetchBids: () => Promise.resolve({ items: [], total: 0 }),
    fetchComparison: () => Promise.resolve(null),
  };
});

vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => 'proj-1',
}));

import { RFQBiddingPage } from '../RFQBiddingPage';
import type { RFQ, RFQStatus } from '../api';

function rfq(id: string, status: RFQStatus): RFQ {
  return {
    id,
    project_id: 'proj-1',
    title: `RFQ ${id}`,
    description: '',
    status,
    due_date: null,
    issued_at: null,
    awarded_at: null,
    currency_code: 'EUR',
    total_estimated: '0',
    vendors_count: 2,
    bids_count: 1,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  };
}

const RFQS = [
  rfq('a', 'draft'),
  rfq('b', 'published'),
  rfq('c', 'bids_received'),
  rfq('d', 'awarded'),
  rfq('e', 'po_issued'),
  rfq('f', 'cancelled'),
];

beforeEach(() => {
  mocks.fetchRFQs.mockResolvedValue({ items: RFQS, total: RFQS.length });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mountPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RFQBiddingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('RFQBiddingPage reads the server RFQ statuses', () => {
  it('counts published and bids received as open, and offers Compare on both', async () => {
    mountPage();
    await waitFor(() => expect(screen.getByText('RFQ b')).toBeTruthy());

    const openCard = screen.getByText('Open').closest('div')!.parentElement!;
    expect(within(openCard).getByText('2')).toBeTruthy();

    // Compare is offered on the two RFQs out with vendors, and on nothing else.
    expect(screen.getAllByRole('button', { name: /Compare/ })).toHaveLength(2);
  });

  it('labels every server status and filters by the server values', async () => {
    mountPage();
    await waitFor(() => expect(screen.getByText('RFQ b')).toBeTruthy());

    for (const label of ['Bids received', 'PO issued', 'Cancelled']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    const values = Array.from(document.querySelectorAll('option')).map((o) => o.getAttribute('value'));
    expect(values).toEqual(
      expect.arrayContaining(['published', 'bids_received', 'po_issued', 'completed', 'cancelled']),
    );
    expect(values).not.toContain('evaluating');
    expect(values).not.toContain('closed');
  });
});
