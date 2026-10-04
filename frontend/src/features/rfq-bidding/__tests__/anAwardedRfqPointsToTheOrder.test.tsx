// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Awarding an RFQ drafts a purchase order for the winning supplier
// (backend/app/modules/procurement/rfq_award.py), stamped with the RFQ's id.
// The Awards tab used to show the winner and stop, then a generic "Raise
// purchase order" link to the bare register. What is pinned: an award whose
// draft is in the register links to that order by number, on the deep link
// the register reads; an award with no order still offers to raise one; an
// RFQ whose order is issued names the order and never offers a second; a
// register that could not be read in full claims nothing; and ?rfq=<id>, the
// way an order links back, opens the Awards tab on that RFQ.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ fetchRFQs: vi.fn(), apiGet: vi.fn() }));

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return { ...actual, apiGet: (url: string, ...rest: unknown[]) => mocks.apiGet(url, ...rest) };
});

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
    rfq_number: `RFQ-${id}`,
    title: `RFQ ${id}`,
    description: '',
    scope_of_work: null,
    submission_deadline: null,
    currency_code: 'EUR',
    status,
    issued_to_contacts: ['vendor-a', 'vendor-b'],
    evaluation_method: 'lowest_price',
    technical_weight: '0',
    require_full_scope: false,
    lines: [],
    bids: [],
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  };
}

function order(id: string, poNumber: string, status: string, rfqId: string) {
  return { id, po_number: poNumber, status, metadata: { origin: 'rfq_award', rfq_id: rfqId } };
}

type OrderRow = ReturnType<typeof order>;

function register(items: OrderRow[], total = items.length) {
  mocks.apiGet.mockImplementation((url: string) => {
    if (url.startsWith('/v1/procurement/')) return Promise.resolve({ items, total, offset: 0, limit: 100 });
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

const scrolled: Element[] = [];

beforeEach(() => {
  mocks.fetchRFQs.mockResolvedValue({
    items: [rfq('won', 'awarded'), rfq('ordered', 'po_issued'), rfq('bare', 'awarded')],
    total: 3,
  });
  scrolled.length = 0;
  Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
    scrolled.push(this);
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mountPage(path = '/rfq-bidding') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <RFQBiddingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function awardCard(title: string): HTMLElement {
  // The card is the bordered block that holds the RFQ's title.
  return screen.getByText(title).closest('div.rounded-xl') as HTMLElement;
}

async function openAwards() {
  await screen.findAllByText('RFQ won');
  fireEvent.click(screen.getByRole('tab', { name: /Awards/ }));
  await screen.findAllByText('RFQ ordered');
}

describe('the awards tab leads to the purchase order the award drafted', () => {
  it('links an award to its draft order, by number, on the register deep link', async () => {
    register([order('po-7', 'PO-0007', 'draft', 'won'), order('po-3', 'PO-0003', 'issued', 'ordered')]);
    mountPage();
    await openAwards();

    const won = within(awardCard('RFQ won'));
    const link = await won.findByRole('link', { name: /PO-0007/ });
    expect(link.getAttribute('href')).toBe('/procurement?po=po-7');
    expect(won.getByText('Draft purchase order created:')).toBeTruthy();
    expect(won.queryByRole('link', { name: /Raise purchase order/ })).toBeNull();
  });

  it('names an issued order without offering a second one', async () => {
    register([order('po-3', 'PO-0003', 'issued', 'ordered')]);
    mountPage();
    await openAwards();

    const ordered = within(awardCard('RFQ ordered'));
    const link = await ordered.findByRole('link', { name: /PO-0003/ });
    expect(link.getAttribute('href')).toBe('/procurement?po=po-3');
    expect(ordered.getByText('Purchase order:')).toBeTruthy();
    expect(ordered.queryByRole('link', { name: /Raise purchase order/ })).toBeNull();
  });

  it('still offers to raise the order when the whole register holds none for the award', async () => {
    register([order('po-3', 'PO-0003', 'issued', 'ordered')]);
    mountPage();
    await openAwards();

    const bare = within(awardCard('RFQ bare'));
    const raise = await bare.findByRole('link', { name: /Raise purchase order/ });
    expect(raise.getAttribute('href')).toBe('/procurement');
  });

  it('passes over a cancelled order, which no longer stands for the award', async () => {
    register([order('po-1', 'PO-0001', 'cancelled', 'won')]);
    mountPage();
    await openAwards();

    const won = within(awardCard('RFQ won'));
    await won.findByRole('link', { name: /Raise purchase order/ });
    expect(won.queryByRole('link', { name: /PO-0001/ })).toBeNull();
  });

  it('claims nothing when the register is longer than the page it read', async () => {
    register([order('po-3', 'PO-0003', 'issued', 'ordered')], 250);
    mountPage();
    await openAwards();

    const bare = within(awardCard('RFQ bare'));
    const find = await bare.findByRole('link', { name: /Find it in Procurement/ });
    expect(find.getAttribute('href')).toBe('/procurement');
    expect(bare.queryByRole('link', { name: /Raise purchase order/ })).toBeNull();
    // The order that is on the page is still named.
    expect(await within(awardCard('RFQ ordered')).findByRole('link', { name: /PO-0003/ })).toBeTruthy();
  });

  it('opens the Awards tab on the RFQ a ?rfq= link names', async () => {
    register([order('po-7', 'PO-0007', 'draft', 'won')]);
    mountPage('/rfq-bidding?rfq=won');

    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /Awards/ }).getAttribute('aria-selected')).toBe('true'),
    );
    // The awards card, not the list row: only the card carries the order link.
    await within(awardCard('RFQ won')).findByRole('link', { name: /PO-0007/ });
    const card = awardCard('RFQ won');
    expect(card.getAttribute('data-focused')).toBe('true');
    await waitFor(() => expect(scrolled).toContain(card));
    expect(awardCard('RFQ bare').getAttribute('data-focused')).toBeNull();
  });

  it('lists Procurement among the related modules', async () => {
    register([]);
    mountPage();
    await screen.findAllByText('RFQ won');

    const link = screen.getByRole('link', { name: 'Procurement' });
    expect(link.getAttribute('href')).toBe('/procurement');
  });
});
