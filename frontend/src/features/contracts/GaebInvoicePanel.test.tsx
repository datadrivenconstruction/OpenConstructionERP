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

  it('sets the outstanding amount beside the net due and says why they differ', async () => {
    previewMock.mockResolvedValue({
      ...preview([]),
      figures: {
        net: '100000.00',
        vat_rate: '19.00',
        vat_amount: '19000.00',
        gross: '119000.00',
        retention: '5000.00',
        release: '20000.00',
        payable: '134000.00',
        outstanding_before_vat: '115000.00',
      },
      claim_net_due: '118000.00',
      warnings: [
        { code: 'outstanding_differs_from_net_due', detail: '', reason: 'stored_materials' },
        { code: 'subcontract_reverse_charge_de', detail: '' },
      ],
      remapped: [{ ordinal: 'A/7', written_as: 'ZZ.Z001', reason: 'ordinal_not_representable' }],
    });
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /GAEB X89 invoice/ }));

    expect(await screen.findByTestId('gaeb-invoice-reconcile')).toBeInTheDocument();
    expect(screen.getByText('Retention released on this claim')).toBeInTheDocument();
    const warnings = screen.getByTestId('gaeb-invoice-warnings');
    expect(warnings).toHaveTextContent('The claim includes materials stored on site, which an X89 does not bill.');
    expect(warnings).toHaveTextContent('section 13b UStG');
    expect(screen.getByTestId('gaeb-invoice-remapped')).toHaveTextContent(
      'A/7 is written as ZZ.Z001 (the OZ has characters GAEB cannot write)',
    );
  });

  it('enables the download when nothing is missing', async () => {
    previewMock.mockResolvedValue(preview([]));
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /GAEB X89 invoice/ }));
    await waitFor(() => expect(screen.getByTestId('gaeb-invoice-download')).toBeEnabled());
    expect(screen.queryByTestId('gaeb-invoice-missing')).toBeNull();
  });
});
