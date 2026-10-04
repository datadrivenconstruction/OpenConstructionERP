// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// An RFQ award records the winner and drafts nothing downstream, so the next
// step is the buyer's: raise the purchase order. The Awards tab showed the
// winner and stopped. What is pinned: an awarded RFQ offers the way to
// Procurement, an RFQ whose order is already issued does not, and the
// page's related-module links include Procurement.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react';
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
    awarded_at: '2026-09-10T00:00:00Z',
    currency_code: 'EUR',
    total_estimated: '0',
    vendors_count: 2,
    bids_count: 1,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  };
}

beforeEach(() => {
  mocks.fetchRFQs.mockResolvedValue({ items: [rfq('won', 'awarded'), rfq('ordered', 'po_issued')], total: 2 });
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

function awardCard(title: string): HTMLElement {
  // The card is the bordered block that holds the RFQ's title.
  return screen.getByText(title).closest('div.rounded-xl') as HTMLElement;
}

describe('the awards tab leads to the purchase order', () => {
  it('offers Procurement on an awarded RFQ and not on one whose order is issued', async () => {
    mountPage();
    await screen.findAllByText('RFQ won');

    fireEvent.click(screen.getByRole('tab', { name: /Awards/ }));

    await screen.findAllByText('RFQ ordered');
    const won = within(awardCard('RFQ won'));
    expect(won.getByRole('link', { name: /Raise purchase order/ }).getAttribute('href')).toBe('/procurement');
    const ordered = within(awardCard('RFQ ordered'));
    expect(ordered.queryByRole('link', { name: /Raise purchase order/ })).toBeNull();
  });

  it('lists Procurement among the related modules', async () => {
    mountPage();
    await screen.findAllByText('RFQ won');

    const link = screen.getByRole('link', { name: 'Procurement' });
    expect(link.getAttribute('href')).toBe('/procurement');
  });
});
