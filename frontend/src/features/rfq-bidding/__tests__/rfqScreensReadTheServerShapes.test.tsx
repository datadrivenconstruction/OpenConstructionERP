// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The RFQ page against the shapes the server really sends.
//
// The page was written for a contract the rfq_bidding module never had: an RFQ
// with due_date, vendors_count and bids_count, bids with vendor_name and
// total_amount, and a comparison "matrix" of bids by scope line. The server
// answers RFQResponse (submission_deadline, issued_to_contacts, embedded bids),
// RFQBidResponse (bidder_contact_id, bid_amount) and ComparisonResponse (ranked
// and excluded quotes restated on one basis currency). The comparison and bid
// list were held on 404s so the page would not crash on them. The fixtures
// below copy the field names of backend/app/modules/rfq_bidding/schemas.py,
// one block per screen: the list, the comparison and the awards.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({
  fetchRFQs: vi.fn(),
  fetchComparison: vi.fn(),
  awardBid: vi.fn(),
  createRFQ: vi.fn(),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchRFQs: (...args: unknown[]) => mocks.fetchRFQs(...args),
    fetchComparison: (...args: unknown[]) => mocks.fetchComparison(...args),
    awardBid: (...args: unknown[]) => mocks.awardBid(...args),
    createRFQ: (...args: unknown[]) => mocks.createRFQ(...args),
  };
});

vi.mock('@/features/contacts/api', () => ({
  fetchContacts: () =>
    Promise.resolve({
      items: [
        { id: 'c-alpha', company_name: 'Alpha Concrete', legal_name: null, first_name: null, last_name: null },
        { id: 'c-beta', company_name: 'Beta Build', legal_name: null, first_name: null, last_name: null },
      ],
      total: 2,
    }),
}));

vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => 'proj-1',
}));

import { RFQBiddingPage } from '../RFQBiddingPage';
import type { Bid, ComparisonResponse, QuoteComparison, RFQ } from '../api';

// RFQBidResponse
function bid(id: string, contact: string, amount: string, awarded = false): Bid {
  return {
    id,
    rfq_id: 'r-open',
    bidder_contact_id: contact,
    bid_amount: amount,
    currency_code: 'EUR',
    submitted_at: '2026-09-10',
    validity_days: 30,
    technical_score: null,
    commercial_score: null,
    notes: awarded ? 'Best price, full scope.' : null,
    is_awarded: awarded,
    status: awarded ? 'awarded' : 'received',
    is_late: false,
    created_at: '2026-09-10T00:00:00Z',
    updated_at: '2026-09-10T00:00:00Z',
  };
}

// RFQResponse
function rfq(id: string, status: RFQ['status'], bids: Bid[]): RFQ {
  return {
    id,
    project_id: 'proj-1',
    rfq_number: `RFQ-${id}`,
    title: `Concrete ${id}`,
    description: null,
    scope_of_work: null,
    submission_deadline: '2026-10-15',
    currency_code: 'EUR',
    status,
    issued_to_contacts: ['c-alpha', 'c-beta', 'c-gamma'],
    evaluation_method: 'lowest_price',
    technical_weight: '0',
    require_full_scope: true,
    lines: [],
    bids,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  };
}

// QuoteComparisonResponse
function quote(bidId: string, contact: string, amount: string | null, rank: number | null, reasons: string[] = []): QuoteComparison {
  return {
    bid_id: bidId,
    bidder_contact_id: contact,
    status: 'received',
    is_late: false,
    admitted: true,
    currency_code: 'EUR',
    headline_amount: amount,
    exchange_rate: null,
    converted_amount: amount,
    adjustments_applied: '0',
    adjustments_included: 0,
    normalised_amount: amount,
    lines_required: 4,
    lines_covered: reasons.length ? 3 : 4,
    coverage: reasons.length ? '0.75' : '1',
    uncovered_lines: [],
    excluded_lines: [],
    extra_lines: 0,
    line_total: amount,
    technical_score: null,
    price_score: null,
    total_score: null,
    comparable: reasons.length === 0,
    reasons,
    notes: [],
    rank,
  };
}

// ComparisonResponse
const COMPARISON: ComparisonResponse = {
  rfq_id: 'r-open',
  rfq_number: 'RFQ-r-open',
  basis_currency: 'EUR',
  method: 'lowest_price',
  technical_weight: '0',
  require_full_scope: true,
  as_of: null,
  lines_required: 4,
  recommended_bid_id: 'b-alpha',
  ranked: [quote('b-alpha', 'c-alpha', '1200.00', 1), quote('b-beta', 'c-beta', '1350.00', 2)],
  excluded: [quote('b-gamma', 'c-gamma', null, null, ['scope_not_covered'])],
};

const RFQS = [
  rfq('r-open', 'bids_received', [bid('b-alpha', 'c-alpha', '1200.00'), bid('b-beta', 'c-beta', '1350.00')]),
  rfq('r-won', 'awarded', [bid('b-won', 'c-beta', '980.00', true), bid('b-lost', 'c-alpha', '1010.00')]),
];

beforeEach(() => {
  mocks.fetchRFQs.mockResolvedValue({ items: RFQS, total: RFQS.length, offset: 0, limit: 50 });
  mocks.fetchComparison.mockResolvedValue(COMPARISON);
  mocks.awardBid.mockResolvedValue(bid('b-alpha', 'c-alpha', '1200.00', true));
  mocks.createRFQ.mockResolvedValue(RFQS[0]);
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

describe('RFQ list screen', () => {
  it('shows the deadline and counts invited contacts and embedded bids', async () => {
    mountPage();
    await waitFor(() => expect(screen.getByText('Concrete r-open')).toBeTruthy());

    expect(screen.getAllByText('3 vendors').length).toBe(2);
    expect(screen.getAllByText('2 bids').length).toBe(2);
    // The deadline line renders only from submission_deadline.
    expect(screen.getAllByText(/Due:/).length).toBe(2);
  });

  it('sends the deadline as submission_deadline when creating an RFQ', async () => {
    mountPage();
    await waitFor(() => expect(screen.getByText('Concrete r-open')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /New RFQ/ }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByPlaceholderText(/Concrete supply/), { target: { value: 'Rebar' } });
    fireEvent.change(dialog.querySelector('input[type="date"]')!, { target: { value: '2026-11-01' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /Create RFQ/ }));

    await waitFor(() => expect(mocks.createRFQ).toHaveBeenCalled());
    const payload = mocks.createRFQ.mock.calls[0]![0];
    expect(payload).toMatchObject({ project_id: 'proj-1', title: 'Rebar', submission_deadline: '2026-11-01' });
    expect('due_date' in payload).toBe(false);
  });
});

describe('RFQ comparison screen', () => {
  it('ranks the quotes by name, marks the recommended one and awards a ranked quote', async () => {
    mountPage();
    await waitFor(() => expect(screen.getByText('Concrete r-open')).toBeTruthy());

    fireEvent.click(screen.getAllByRole('button', { name: /Compare/ })[0]!);

    await waitFor(() => expect(screen.getByText('Alpha Concrete')).toBeTruthy());
    expect(mocks.fetchComparison).toHaveBeenCalledWith('r-open');
    const alphaRow = screen.getByText('Alpha Concrete').closest('tr')!;
    expect(within(alphaRow).getByText('Recommended')).toBeTruthy();
    expect(within(alphaRow).getByText('4/4')).toBeTruthy();
    expect(screen.getByText('Beta Build').closest('tr')).toBeTruthy();

    fireEvent.click(within(alphaRow).getByRole('button', { name: /Award to Alpha Concrete/ }));
    await waitFor(() => expect(mocks.awardBid).toHaveBeenCalledWith('b-alpha'));
  });

  it('lists an excluded quote with its reason and offers no award for it', async () => {
    mountPage();
    await waitFor(() => expect(screen.getByText('Concrete r-open')).toBeTruthy());

    fireEvent.click(screen.getAllByRole('button', { name: /Compare/ })[0]!);

    await waitFor(() => expect(screen.getByText('Not comparable')).toBeTruthy());
    // c-gamma is not in the contacts page, so the id itself is shown.
    expect(screen.getByText('c-gamma')).toBeTruthy();
    expect(screen.getByText('Part of the scope is not priced')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Award to c-gamma/ })).toBeNull();
  });
});

describe('RFQ awards screen', () => {
  it('names the winning bidder and amount from the RFQ embedded bids', async () => {
    mountPage();
    await waitFor(() => expect(screen.getByText('Concrete r-open')).toBeTruthy());

    fireEvent.click(screen.getByRole('tab', { name: /Awards/ }));

    await waitFor(() => expect(screen.getByText('Concrete r-won')).toBeTruthy());
    expect(screen.getByText('Beta Build')).toBeTruthy();
    expect(screen.getByText('Best price, full scope.')).toBeTruthy();
    expect(screen.queryByText('Alpha Concrete')).toBeNull();
  });
});
