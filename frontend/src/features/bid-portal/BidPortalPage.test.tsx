// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The public price-entry page a subcontractor opens from the invitation link.
//
// The bidder has nobody to ask, so the page itself has to keep them out of
// the two mistakes that cost a tender: submitting an empty bid, and believing
// a submitted bid can still be changed. The sum they see has to be the sum of
// what they typed, line by line, in the tender currency.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { formatCurrency } from '@/shared/lib/money';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

// `src/test/setup.ts` mocks `useParams` to `{}`; without a token the page
// shows the broken-link screen and never fetches.
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({ token: 'bidder-link-token' }),
  };
});

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return { ...actual, fetchBidPortal: vi.fn(), saveBidDraft: vi.fn(), submitBid: vi.fn() };
});

import { BidPortalError, fetchBidPortal, submitBid } from './api';
import type { BidPortalView } from './api';
import { BidPortalPage } from './BidPortalPage';

const fetchMock = vi.mocked(fetchBidPortal);
const submitMock = vi.mocked(submitBid);

const LOCALE = 'en-US';

function makeView(overrides: Partial<BidPortalView> = {}): BidPortalView {
  return {
    state: 'open',
    package_name: 'Earthworks package',
    package_description: '',
    deadline: null,
    currency: 'EUR',
    project_name: 'Office block',
    buyer_name: 'Main contractor',
    bidder_company: 'Digging Ltd',
    expires_at: '2030-01-01T00:00:00Z',
    lines: [
      { id: 's1', kind: 'section', ordinal: '01', short_text: 'Earthworks', long_text: '', unit: '', quantity: '', depth: 0 },
      {
        id: 'p1',
        kind: 'item',
        ordinal: '01.001',
        short_text: 'Excavate trench',
        long_text: 'Excavate trench in soil class 3-5, depth up to 1.25 m.',
        unit: 'm3',
        quantity: '10',
        depth: 1,
      },
      { id: 'p2', kind: 'item', ordinal: '01.002', short_text: 'Backfill', long_text: '', unit: 'm3', quantity: '2.5', depth: 1 },
    ],
    draft: { unit_prices: {}, notes: '', saved_at: null },
    submitted_at: null,
    bid_amount: null,
    item_count: 2,
    unpriced_count: 2,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <BidPortalPage />
    </MemoryRouter>,
  );
}

/** `textContent` keeps the formatter's non-breaking spaces, which a text query would not. */
function sumText(): string {
  return screen.getByTestId('bid-portal-sum').textContent ?? '';
}

beforeEach(() => {
  vi.clearAllMocks();
  usePreferencesStore.setState({ numberLocale: LOCALE });
});

describe('the bidder price-entry page', () => {
  it('renders the bill: section heading, items, units, quantities and the long text on demand', async () => {
    fetchMock.mockResolvedValue(makeView());
    renderPage();

    await screen.findByTestId('bid-portal-table');
    expect(screen.getByTestId('bid-portal-title').textContent).toContain('Earthworks package');
    expect(screen.getByText('Earthworks')).toBeTruthy();
    expect(screen.getByText('Excavate trench')).toBeTruthy();
    expect(screen.getByText('Backfill')).toBeTruthy();
    expect(screen.getByTestId('bid-price-input-01.001')).toBeTruthy();
    expect(screen.getByTestId('bid-price-input-01.002')).toBeTruthy();
    // The heading row carries no price field.
    expect(screen.queryByTestId('bid-price-input-01')).toBeNull();

    expect(screen.queryByText(/soil class 3-5/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /show full text/i }));
    expect(screen.getByText(/soil class 3-5/)).toBeTruthy();
  });

  it('updates the line sums and the bid sum as prices are typed', async () => {
    fetchMock.mockResolvedValue(makeView());
    renderPage();
    await screen.findByTestId('bid-portal-table');

    expect(sumText()).toContain(formatCurrency(0, 'EUR', LOCALE));

    fireEvent.change(screen.getByTestId('bid-price-input-01.001'), { target: { value: '12.5' } });
    // 10 m3 x 12.50
    expect(sumText()).toContain(formatCurrency(125, 'EUR', LOCALE));

    fireEvent.change(screen.getByTestId('bid-price-input-01.002'), { target: { value: '4' } });
    // 125 + 2.5 m3 x 4.00
    expect(sumText()).toContain(formatCurrency(135, 'EUR', LOCALE));
    expect(screen.getByTestId('bid-portal-progress').textContent).toContain('2 of 2');

    fireEvent.change(screen.getByTestId('bid-price-input-01.001'), { target: { value: '' } });
    expect(sumText()).toContain(formatCurrency(10, 'EUR', LOCALE));
  });

  it('keeps submit disabled until a price is entered, and while a price is not a valid number', async () => {
    fetchMock.mockResolvedValue(makeView());
    renderPage();
    await screen.findByTestId('bid-portal-table');

    const submit = screen.getByTestId('bid-portal-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByTestId('bid-price-input-01.001'), { target: { value: '-3' } });
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByTestId('bid-price-input-01.001'), { target: { value: '3' } });
    expect(submit.disabled).toBe(false);
  });

  it('submits after the confirmation and then shows a read-only receipt', async () => {
    fetchMock.mockResolvedValue(makeView());
    submitMock.mockResolvedValue(
      makeView({
        state: 'submitted',
        submitted_at: '2026-10-04T10:00:00Z',
        bid_amount: '125.00',
        unpriced_count: 1,
        draft: { unit_prices: { p1: '12.5' }, notes: '', saved_at: '2026-10-04T10:00:00Z' },
      }),
    );
    renderPage();
    await screen.findByTestId('bid-portal-table');

    fireEvent.change(screen.getByTestId('bid-price-input-01.001'), { target: { value: '12.5' } });
    fireEvent.click(screen.getByTestId('bid-portal-submit'));

    const dialog = await screen.findByRole('alertdialog');
    // One line left unpriced is said out loud before the bid goes in.
    expect(dialog.textContent).toContain('1 line has no price');
    fireEvent.click(within(dialog).getByTestId('confirm-dialog-confirm'));

    await screen.findByTestId('bid-portal-receipt');
    expect(submitMock).toHaveBeenCalledTimes(1);
    const [token, body] = submitMock.mock.calls[0]!;
    expect(token).toBe('bidder-link-token');
    expect(body.unit_prices).toEqual({ p1: '12.5' });
    expect(body.currency).toBe('EUR');

    expect((screen.getByTestId('bid-price-input-01.001') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByTestId('bid-price-input-01.002') as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByTestId('bid-portal-submit')).toBeNull();
    expect(screen.queryByTestId('bid-portal-save')).toBeNull();
  });

  it('opens an already submitted link as a receipt with nothing to edit', async () => {
    fetchMock.mockResolvedValue(
      makeView({
        state: 'submitted',
        submitted_at: '2026-10-01T08:30:00Z',
        bid_amount: '135.00',
        unpriced_count: 0,
        draft: { unit_prices: { p1: '12.5', p2: '4' }, notes: '', saved_at: '2026-10-01T08:30:00Z' },
      }),
    );
    renderPage();

    const receipt = await screen.findByTestId('bid-portal-receipt');
    expect(receipt.textContent).toContain(formatCurrency('135.00', 'EUR', LOCALE));
    const input = screen.getByTestId('bid-price-input-01.001') as HTMLInputElement;
    expect(input.value).toBe('12.5');
    expect(input.disabled).toBe(true);
    expect(screen.queryByTestId('bid-portal-submit')).toBeNull();
  });

  it.each([
    ['expired', 410],
    ['revoked', 410],
    ['not_found', 404],
  ] as const)('shows the %s link state instead of the bill', async (code, status) => {
    fetchMock.mockRejectedValue(new BidPortalError(code, status));
    renderPage();

    await screen.findByTestId(`bid-portal-link-${code}`);
    expect(screen.queryByTestId('bid-portal-table')).toBeNull();
  });

  it('keeps what the bidder typed when the server refuses the submission', async () => {
    fetchMock.mockResolvedValue(makeView());
    submitMock.mockRejectedValue(
      new BidPortalError('invalid_prices', 422, [{ line_id: 'p1', reason: 'too_many_decimals' }]),
    );
    renderPage();
    await screen.findByTestId('bid-portal-table');

    fireEvent.change(screen.getByTestId('bid-price-input-01.001'), { target: { value: '1.123456' } });
    fireEvent.click(screen.getByTestId('bid-portal-submit'));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByTestId('confirm-dialog-confirm'));

    await waitFor(() => expect(screen.getByTestId('bid-portal-action-error')).toBeTruthy());
    const input = screen.getByTestId('bid-price-input-01.001') as HTMLInputElement;
    expect(input.value).toBe('1.123456');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(input.disabled).toBe(false);
  });
});
