// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// <GaebInvoicePanel> asks the server nothing until it is opened, shows the
// figures and the VAT source exactly as the server computed them, and keeps
// the download disabled while a mandatory field is missing, naming it.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/features/boq/gaebSiteExchangeApi', () => ({
  previewClaimInvoice: vi.fn(),
  downloadClaimInvoice: vi.fn(),
}));

import * as api from '@/features/boq/gaebSiteExchangeApi';
import { GaebInvoicePanel } from './GaebInvoicePanel';

const previewMock = vi.mocked(api.previewClaimInvoice);

const PARTY = { name: 'Rohbau Nord GmbH', street: 'Hafenweg 4', postcode: '20457', city: 'Hamburg', country: 'DE', tax_no: '', vat_id: 'DE1' };

function preview(missing: string[]): api.ClaimInvoicePreview {
  return {
    claim_id: 'c1',
    claim_number: 'AR-2',
    contract_code: 'V-1',
    invoice_type: 'deduction',
    invoice_date: '2026-09-30',
    period_start: '2026-09-01',
    period_end: '2026-09-30',
    currency: 'EUR',
    line_count: 2,
    figures: { net: '10100.00', vat_rate: '19.00', vat_amount: '1919.00', gross: '12019.00', retention: '505.00', payable: '11514.00' },
    vat_source: 'boq_tax_markup',
    creator: PARTY,
    recipient: { ...PARTY, name: 'Stadt Musterstadt', street: '' },
    missing,
    warnings: [],
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GaebInvoicePanel claimId="c1" claimNumber="AR-2" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  previewMock.mockReset();
});

describe('GaebInvoicePanel', () => {
  it('asks nothing while collapsed', () => {
    renderPanel();
    expect(previewMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId('gaeb-invoice-download')).toBeNull();
  });

  it('names what is missing and keeps the download disabled', async () => {
    previewMock.mockResolvedValue(preview(['recipient.street']));
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /GAEB X89 invoice/ }));

    await waitFor(() => expect(previewMock).toHaveBeenCalledWith('c1', ''));
    expect(await screen.findByText('Invoice recipient: street')).toBeInTheDocument();
    expect(screen.getByText('VAT 19.00 % (tax markup of the bill)')).toBeInTheDocument();
    expect(screen.getByTestId('gaeb-invoice-download')).toBeDisabled();
  });

  it('enables the download when nothing is missing', async () => {
    previewMock.mockResolvedValue(preview([]));
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /GAEB X89 invoice/ }));
    await waitFor(() => expect(screen.getByTestId('gaeb-invoice-download')).toBeEnabled());
    expect(screen.queryByTestId('gaeb-invoice-missing')).toBeNull();
  });
});
