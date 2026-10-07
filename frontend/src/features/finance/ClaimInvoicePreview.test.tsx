// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for <ClaimInvoicePreview>.
//
// A 120,000 EUR subcontract at 5% retention, first claim at 30%: the invoice
// carries a gross of 36,000 and holds 1,800, so 34,200 changes hands now.
//
//   * a subcontractor's claim reads as a payable, and the figure under the
//     line is the gross less retention, not the stored subtotal (the gross);
//   * a claim certified after the page first asked is not stuck on
//     "Not raised": a certified claim looks again until the invoice lands.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

import * as api from '@/shared/lib/api';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { ClaimInvoicePreview } from './ClaimInvoicePreview';

// No i18n instance is set up here, so labels render as their keys.

const getMock = vi.mocked(api.apiGet);

const payable = {
  id: 'inv-1',
  invoice_number: 'INV-P-001',
  status: 'draft',
  currency_code: 'EUR',
  amount_subtotal: '36000.00',
  retention_amount: '1800.00',
  amount_total: '36000.00',
  invoice_direction: 'payable',
  source_claim_id: 'claim-1',
};

function renderPreview(props: Partial<Parameters<typeof ClaimInvoicePreview>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <ClaimInvoicePreview claimId="claim-1" certified {...props} />
    </QueryClientProvider>,
  );
  return { ...view, qc };
}

const absent = () => new api.ApiError(404, 'Not Found', {
  detail: 'No receivable invoice exists for this claim',
});

beforeEach(() => {
  vi.clearAllMocks();
  getMock.mockReset();
  usePreferencesStore.setState({ numberLocale: 'en-US' });
});

describe('ClaimInvoicePreview', () => {
  // These wire-value fixtures exercise frontend precision only, not backend storage scale.
  it.each([
    ['JPY', '1000', '1', '\u00a5999'],
    ['USD', '10.00', '0.01', '$9.99'],
    ['KWD', '10.000', '0.001', 'KWD9.999'],
    ['USD', '9007199254740993.01', '0.01', '$9,007,199,254,740,993.00'],
    ['USD', '10.0000', '1.0000', '$9.00'],
    ['USD', '0.00', '0.01', '-$0.01'],
    ['USD', 'invalid', '0.01', '\u2014'],
  ])('renders exact net for %s gross=%s retention=%s', async (currency, gross, retention, expected) => {
    getMock.mockResolvedValue({ ...payable, currency_code: currency, amount_total: gross, retention_amount: retention });
    renderPreview({ direction: 'payable' });
    await screen.findByText('INV-P-001');
    const row = screen.getByText('finance.claimInvoice.netPayable').parentElement;
    expect(row?.querySelector('dd')?.textContent?.replace(/\s/g, '')).toBe(expected);
  });

  it('shows a subcontract claim as a payable with the net after retention', async () => {
    getMock.mockResolvedValue(payable);
    renderPreview({ direction: 'payable' });

    expect(await screen.findByText('INV-P-001')).toBeInTheDocument();
    expect(screen.getByText('finance.claimInvoice.titlePayable')).toBeInTheDocument();
    expect(screen.getByText('finance.claimInvoice.netPayable')).toBeInTheDocument();
    expect(screen.getByText(/34\D?200/)).toBeInTheDocument();
    expect(screen.queryByText('finance.claimInvoice.netCollectible')).not.toBeInTheDocument();
  });

  it('shows a client claim as collectible after retention, never the gross subtotal', async () => {
    // P-39: the card used to print the stored subtotal, which is the gross,
    // as the net collectible (184,300 on a certified client claim).
    getMock.mockResolvedValue({
      ...payable,
      invoice_number: 'INV-R-007',
      amount_subtotal: '184300.00',
      retention_amount: '9215.00',
      amount_total: '184300.00',
      invoice_direction: 'receivable',
    });
    renderPreview({ direction: 'receivable' });

    expect(await screen.findByText('INV-R-007')).toBeInTheDocument();
    const net = screen.getByText('finance.claimInvoice.netCollectible').parentElement as HTMLElement;
    expect(net).toHaveTextContent(/175\D?085/);
    expect(net).not.toHaveTextContent(/184\D?300/);
  });

  it('offers to raise a payable before the invoice exists', async () => {
    getMock.mockRejectedValue(absent());
    renderPreview({ direction: 'payable', certified: false });

    expect(await screen.findByText('finance.claimInvoice.raiseActionPayable')).toBeInTheDocument();
  });

  it('keeps looking for the invoice a certified claim raises', async () => {
    getMock.mockRejectedValueOnce(absent()).mockResolvedValue(payable);
    renderPreview({ direction: 'payable' });

    await waitFor(() => expect(screen.getByText('INV-P-001')).toBeInTheDocument(), { timeout: 6000 });
    expect(getMock).toHaveBeenCalledTimes(2);
  }, 10000);

  it.each([
    ['forbidden', new api.ApiError(403, 'Forbidden', { detail: 'Denied' })],
    ['server failure', new api.ApiError(500, 'Server Error', { detail: 'Unavailable' })],
    ['network failure', new Error('Network unavailable')],
    ['unrelated 404', new api.ApiError(404, 'Not Found', { detail: 'Claim not found' })],
  ])('shows %s as a retryable error, never as an absent invoice', async (_name, failure) => {
    getMock.mockRejectedValue(failure);
    renderPreview();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'common.retry' })).toBeInTheDocument();
    expect(screen.queryByText('finance.claimInvoice.notRaised')).not.toBeInTheDocument();
    expect(screen.queryByText('finance.claimInvoice.raiseAction')).not.toBeInTheDocument();
  });

  it('does not claim absence while the lookup is pending', () => {
    getMock.mockReturnValue(new Promise(() => {}));
    renderPreview();
    expect(screen.queryByText('finance.claimInvoice.notRaised')).not.toBeInTheDocument();
    expect(screen.queryByText('finance.claimInvoice.raiseAction')).not.toBeInTheDocument();
  });

  it('retries a failed lookup and displays the recovered invoice', async () => {
    getMock.mockRejectedValueOnce(new Error('Offline')).mockResolvedValue(payable);
    renderPreview();
    fireEvent.click(await screen.findByRole('button', { name: 'common.retry' }));
    expect(await screen.findByText('INV-P-001')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('hides stale invoice details when refetch fails and allows recovery', async () => {
    getMock.mockResolvedValueOnce(payable).mockRejectedValueOnce(new Error('Offline')).mockResolvedValue(payable);
    const { qc } = renderPreview();
    await screen.findByText('INV-P-001');
    await act(async () => { await qc.invalidateQueries({ queryKey: ['finance', 'claim-receivable'] }); });
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('INV-P-001')).not.toBeInTheDocument();
    expect(screen.queryByText('finance.claimInvoice.raised')).not.toBeInTheDocument();
    expect(screen.queryByText('finance.claimInvoice.notRaised')).not.toBeInTheDocument();
    expect(screen.queryByText('finance.claimInvoice.raiseAction')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(await screen.findByText('INV-P-001')).toBeInTheDocument();
  });

  it('does not poll failed lookups as though an invoice were absent', async () => {
    getMock.mockRejectedValue(new Error('Offline'));
    renderPreview();
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 3200)); });
    expect(getMock).toHaveBeenCalledTimes(1);
  }, 10000);
});
