// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The bidder's file side of a link: a priced X84 is checked first and every
// line that does not fit the bill is named, so a wrong file is never submitted;
// a firm that will not bid says why; the tender documents are one click away.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return { ...actual, checkBidX84: vi.fn(), submitBidX84: vi.fn(), declineBid: vi.fn(), uploadBidFile: vi.fn() };
});

import { checkBidX84, declineBid, submitBidX84 } from './api';
import type { BidPortalView, X84Preview } from './api';
import { BidExchangeSection } from './BidExchangeSection';

function makeView(overrides: Partial<BidPortalView> = {}): BidPortalView {
  return {
    state: 'open',
    package_name: 'Earthworks',
    package_description: '',
    deadline: null,
    currency: 'EUR',
    project_name: 'Office block',
    buyer_name: 'Main contractor',
    bidder_company: 'Digging Ltd',
    expires_at: '2030-01-01T00:00:00Z',
    lines: [],
    draft: { unit_prices: {}, notes: '', saved_at: null },
    submitted_at: null,
    bid_amount: null,
    item_count: 2,
    unpriced_count: 2,
    files: [],
    documents: [],
    ...overrides,
  };
}

function preview(overrides: Partial<X84Preview> = {}): X84Preview {
  return {
    filename: 'offer.X84',
    sha256: 'abc',
    file_issues: [],
    lines: [
      { ordinal: '01.0010', position_id: 'p1', description: 'Excavate', unit: 'm3', quantity: '120.5', unit_rate: '21.40', issues: [] },
      { ordinal: '01.0020', position_id: 'p2', description: 'Backfill', unit: 'm2', quantity: '80', unit_rate: '9.95', issues: ['unit_mismatch'] },
    ],
    matched: 2,
    priced: 2,
    missing_ordinals: [],
    total_amount: '3374.70',
    blocking: true,
    ...overrides,
  };
}

function pickX84() {
  const input = screen.getByTestId('bid-x84-input') as HTMLInputElement;
  const file = new File(['<GAEB/>'], 'offer.X84', { type: 'application/xml' });
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  vi.mocked(checkBidX84).mockReset();
  vi.mocked(submitBidX84).mockReset();
  vi.mocked(declineBid).mockReset();
});

describe('BidExchangeSection', () => {
  it('names every X84 line that does not fit and will not submit the file', async () => {
    vi.mocked(checkBidX84).mockResolvedValue(preview());
    render(<BidExchangeSection token="t" view={makeView()} onView={vi.fn()} />);
    pickX84();
    const table = await screen.findByTestId('bid-x84-mismatches');
    expect(table.textContent).toContain('01.0020');
    expect(table.textContent).toContain('Unit differs from the bill');
    expect(table.textContent).not.toContain('01.0010');
    expect(screen.getByRole('button', { name: /Submit bid from this file/ })).toBeDisabled();
    expect(submitBidX84).not.toHaveBeenCalled();
  });

  it('submits a clean X84 and hands the new view back', async () => {
    const clean = preview({ blocking: false, lines: [preview().lines[0]!] });
    vi.mocked(checkBidX84).mockResolvedValue(clean);
    const submitted = makeView({ state: 'submitted' });
    vi.mocked(submitBidX84).mockResolvedValue(submitted);
    const onView = vi.fn();
    render(<BidExchangeSection token="t" view={makeView()} onView={onView} />);
    pickX84();
    const button = await screen.findByRole('button', { name: /Submit bid from this file/ });
    fireEvent.click(button);
    await waitFor(() => expect(onView).toHaveBeenCalledWith(submitted));
  });

  it('asks for a reason before a decline can be sent', async () => {
    const declined = makeView({ state: 'declined', decline_reason: 'No capacity' });
    vi.mocked(declineBid).mockResolvedValue(declined);
    const onView = vi.fn();
    render(<BidExchangeSection token="t" view={makeView()} onView={onView} />);
    fireEvent.click(screen.getByRole('button', { name: /We will not bid/ }));
    const send = screen.getByRole('button', { name: /Send decline/ });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Why not/), { target: { value: 'No capacity' } });
    fireEvent.click(send);
    await waitFor(() => expect(declineBid).toHaveBeenCalledWith('t', 'No capacity'));
    expect(onView).toHaveBeenCalledWith(declined);
  });

  it('shows a declined link with its reason and no upload buttons', () => {
    render(
      <BidExchangeSection token="t" view={makeView({ state: 'declined', decline_reason: 'No capacity' })} onView={vi.fn()} />,
    );
    expect(screen.getByTestId('bid-portal-declined').textContent).toContain('No capacity');
    expect(screen.queryByTestId('bid-x84-input')).toBeNull();
  });

  it('links each tender document to its download through the token', () => {
    render(
      <BidExchangeSection
        token="tok"
        view={makeView({ documents: [{ id: 'd1', name: 'Conditions.pdf', file_size: 2048, mime_type: 'application/pdf' }] })}
        onView={vi.fn()}
      />,
    );
    const link = screen.getByRole('link', { name: /Download/ });
    expect(link.getAttribute('href')).toBe('/api/v1/tendering/bid-portal/tok/documents/d1/');
    expect(screen.getByTestId('bid-portal-documents').textContent).toContain('Conditions.pdf');
  });
});
