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
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

import * as api from '@/shared/lib/api';
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
  return render(
    <QueryClientProvider client={qc}>
      <ClaimInvoicePreview claimId="claim-1" certified {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ClaimInvoicePreview', () => {
  it('shows a subcontract claim as a payable with the net after retention', async () => {
    getMock.mockResolvedValue(payable);
    renderPreview({ direction: 'payable' });

    expect(await screen.findByText('INV-P-001')).toBeInTheDocument();
    expect(screen.getByText('finance.claimInvoice.titlePayable')).toBeInTheDocument();
    expect(screen.getByText('finance.claimInvoice.netPayable')).toBeInTheDocument();
    expect(screen.getByText(/34\D?200/)).toBeInTheDocument();
    expect(screen.queryByText('finance.claimInvoice.netCollectible')).not.toBeInTheDocument();
  });

  it('offers to raise a payable before the invoice exists', async () => {
    getMock.mockRejectedValue(new Error('404'));
    renderPreview({ direction: 'payable', certified: false });

    expect(await screen.findByText('finance.claimInvoice.raiseActionPayable')).toBeInTheDocument();
  });

  it('keeps looking for the invoice a certified claim raises', async () => {
    getMock.mockRejectedValueOnce(new Error('404')).mockResolvedValue(payable);
    renderPreview({ direction: 'payable' });

    await waitFor(() => expect(screen.getByText('INV-P-001')).toBeInTheDocument(), { timeout: 6000 });
    expect(getMock).toHaveBeenCalledTimes(2);
  }, 10000);
});
