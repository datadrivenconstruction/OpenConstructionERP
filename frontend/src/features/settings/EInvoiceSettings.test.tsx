// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Component tests for <EInvoiceSettings>.
//
// This screen exists because the compliance panel on an invoice reported fatal
// EN 16931 violations the user had no way to fix. So the behaviour worth
// pinning is not that the inputs render, it is that the screen tells the user
// which fields still block an invoice, and that a value the server refuses is
// shown rather than swallowed.
//
// The IBAN check lives on the server on purpose, so there is exactly one copy
// of the rule. That makes the error path load-bearing here: if this component
// dropped the API's message, a mistyped account would look saved and the panel
// on the invoice would go on demanding an account the user believes is set.
//
// The i18n mock in src/test/setup.ts returns the key itself when a call passes
// no defaultValue, so the keys below are what the component renders here.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToString } from 'react-dom/server';

// Only the two calls this panel makes are replaced. The rest of the module
// stays real because <Button> comes from the shared barrel, which drags in
// every component beside it, and several of those read API_BASE or ApiError at
// module-eval time.
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPut: vi.fn() };
});

import { EInvoiceSettings } from './EInvoiceSettings';
import * as api from '@/shared/lib/api';

const apiGetMock = vi.mocked(api.apiGet);
const apiPutMock = vi.mocked(api.apiPut);

const BLANK = {
  seller_name: '',
  seller_vat_id: '',
  seller_tax_number: '',
  seller_legal_id: '',
  seller_country_code: '',
  seller_line1: '',
  seller_postcode: '',
  seller_city: '',
  // BG-6, the seller contact XRechnung requires (BR-DE-2, BR-DE-5..7).
  seller_contact_name: '',
  seller_contact_phone: '',
  seller_contact_email: '',
  seller_email: '',
  seller_electronic_address: '',
  seller_electronic_address_scheme: '',
  payee_iban: '',
  payee_bic: '',
  payee_account_name: '',
  payment_means_code: '',
  payment_terms: '',
  complete: false,
  missing: ['seller_name', 'seller_country_code', 'seller_vat_id'],
  // Served by the API with every answer, cut here to what the assertions
  // need: the panel labels the account field by whether the seller's country
  // is in this list, so a fixture without it asks for an "account number" and
  // the IBAN label these tests look for never renders.
  iban_countries: ['DE', 'AT', 'NL', 'FR'],
};

const CONFIGURED = {
  ...BLANK,
  seller_name: 'Hochbau Nord GmbH',
  seller_vat_id: 'DE123456789',
  seller_country_code: 'DE',
  payee_iban: 'DE02120300000000202051',
  complete: true,
  missing: [],
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EInvoiceSettings />
    </QueryClientProvider>,
  );
}

describe('EInvoiceSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiPutMock.mockResolvedValue(CONFIGURED);
  });

  it('names the fields that still stop an invoice being issued', async () => {
    apiGetMock.mockResolvedValue(BLANK);
    renderPanel();

    await screen.findByText('settings.einvoice.incomplete');
    // Asserted as the one joined string rather than field by field, because
    // each of these labels also appears on its own input and a loose match
    // would find the form rather than the warning.
    await screen.findByText(
      'settings.einvoice.field.seller_name, settings.einvoice.field.seller_country_code, ' +
        'settings.einvoice.field.seller_vat_id',
    );
    expect(screen.queryByText('settings.einvoice.ready')).toBeNull();
  });

  it('says the configuration is enough once nothing is missing', async () => {
    apiGetMock.mockResolvedValue(CONFIGURED);
    renderPanel();

    await screen.findByText('settings.einvoice.ready');
    expect(screen.queryByText('settings.einvoice.incomplete')).toBeNull();
  });

  it('fills the form from what is stored', async () => {
    apiGetMock.mockResolvedValue(CONFIGURED);
    renderPanel();

    const name = (await screen.findByLabelText('settings.einvoice.field.seller_name')) as HTMLInputElement;
    expect(name.value).toBe('Hochbau Nord GmbH');
    const iban = screen.getByLabelText('settings.einvoice.field.payee_iban') as HTMLInputElement;
    expect(iban.value).toBe('DE02120300000000202051');
  });

  // What this pins is that the very first render is already consistent with the
  // answer, rather than becoming consistent afterwards. It cannot be checked by
  // rendering into the DOM and looking: every helper here runs inside act, which
  // flushes effects before it returns, so a panel that fills itself from an
  // effect looks identical to one that does not. Rendering to a string is the
  // one place effects do not run at all, so it separates the two by
  // construction instead of by timing.
  //
  // The defect it stands for is one frame long. The panel used to fill the form
  // from an effect, so on the frame between the answer arriving and the effect
  // running, every field differed from an empty form, the panel believed it held
  // unsaved edits, and the save button offered to save a change nobody had made.
  // A fast machine never showed it and the CI runner did.
  it('is already consistent with the stored values on its first render', () => {
    apiGetMock.mockResolvedValue(CONFIGURED);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(['finance', 'einvoice-settings'], CONFIGURED);
    const html = renderToString(
      <QueryClientProvider client={client}>
        <EInvoiceSettings />
      </QueryClientProvider>,
    );

    expect(html).toContain('Hochbau Nord GmbH');
    // The button carries the attribute only while it refuses to be pressed, so
    // its absence is the defect rather than a difference in how it is spelled.
    expect(html).toMatch(/<button[^>]*\sdisabled/);
  });

  it('does not offer to save until something has changed', async () => {
    apiGetMock.mockResolvedValue(CONFIGURED);
    renderPanel();

    const save = await screen.findByRole('button', { name: 'settings.einvoice.save' });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText('settings.einvoice.field.seller_city'), {
      target: { value: 'Kiel' },
    });
    await waitFor(() => expect(save).toBeEnabled());
  });

  it('sends the whole configuration, so a cleared field is cleared', async () => {
    apiGetMock.mockResolvedValue(CONFIGURED);
    renderPanel();

    const iban = await screen.findByLabelText('settings.einvoice.field.payee_iban');
    fireEvent.change(iban, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'settings.einvoice.save' }));

    await waitFor(() => expect(apiPutMock).toHaveBeenCalledTimes(1));
    const [url, body] = apiPutMock.mock.calls[0]!;
    expect(url).toBe('/api/v1/finance/einvoice-settings');
    // Present and empty, not absent: a patch could not express a removal.
    expect(body).toHaveProperty('payee_iban', '');
    expect(body).toHaveProperty('seller_name', 'Hochbau Nord GmbH');
  });

  it("labels the account the way the seller's country is paid", async () => {
    // The IBAN check is strict on the server, so the label has to say what the
    // server will judge the value as. A seller outside the IBAN area is asked
    // for an account number; typing a country inside it flips the label at
    // once, because the country is read off the form and not off the saved
    // row, and the same moment is when the server starts judging the account.
    apiGetMock.mockResolvedValue({ ...CONFIGURED, seller_country_code: 'US', payee_iban: '021000021' });
    renderPanel();

    await screen.findByLabelText('settings.einvoice.field.payee_account_number');
    expect(screen.queryByLabelText('settings.einvoice.field.payee_iban')).toBeNull();

    fireEvent.change(screen.getByLabelText('settings.einvoice.field.seller_country_code'), {
      target: { value: 'DE' },
    });
    await screen.findByLabelText('settings.einvoice.field.payee_iban');
    expect(screen.queryByLabelText('settings.einvoice.field.payee_account_number')).toBeNull();
  });

  it('shows what the server said about a refused account number', async () => {
    apiGetMock.mockResolvedValue(CONFIGURED);
    apiPutMock.mockRejectedValue(
      new Error('the check digits of "DE02120300000000202052" do not match the rest of the account number'),
    );
    renderPanel();

    const iban = await screen.findByLabelText('settings.einvoice.field.payee_iban');
    fireEvent.change(iban, { target: { value: 'DE02120300000000202052' } });
    fireEvent.click(screen.getByRole('button', { name: 'settings.einvoice.save' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('check digits');
  });
});
