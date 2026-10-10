// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Component tests for the UBL-TR (e-Fatura) path of <EInvoiceModal>.
//
// A Turkish sales invoice is exported as an unsigned XML that a licensed
// integrator signs and submits. What can go wrong on this screen is quiet in
// every case: a German profile checked first for a Turkish seller, a download
// offered on a verdict that was reached before the last edit, a save that
// clears the fields the form does not show, an amount recomputed on this side
// that no longer matches the payment certificate. None of those raises an
// error, so each is pinned by what was asked of the server and what is on
// screen.
//
// The i18n mock in src/test/setup.ts returns the key itself when a call passes
// no defaultValue, so the keys below are what the component renders here.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Only the calls this panel makes are replaced; see EInvoiceModal.test.tsx for
// why the rest of the module has to stay real.
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: vi.fn(),
    apiPut: vi.fn(),
    apiPatch: vi.fn(),
    downloadWithAuth: vi.fn(),
  };
});

import { EInvoiceModal } from './EInvoiceModal';
import type { EInvoiceDryRun, EInvoiceViolation, TrEInvoiceFields } from './api';
import * as api from '@/shared/lib/api';

const apiGetMock = vi.mocked(api.apiGet);
const apiPutMock = vi.mocked(api.apiPut);
const apiPatchMock = vi.mocked(api.apiPatch);
const downloadMock = vi.mocked(api.downloadWithAuth);

const INVOICE_ID = 'inv-1';

const REGISTRY = [
  { key: 'xrechnung', label: 'XRechnung 3.0', syntax: 'cii', region: 'DE' },
  { key: 'peppol', label: 'Peppol BIS Billing 3.0', syntax: 'ubl', region: 'international' },
  { key: 'ubl_tr', label: 'UBL-TR 1.2 (e-Fatura / e-Arşiv Fatura, unsigned)', syntax: 'ubl_tr', region: 'TR' },
];

const FIELDS: TrEInvoiceFields = {
  profile_id: '',
  invoice_type: '',
  document_id: '',
  series: '',
  issue_time: '',
  exchange_rate: '',
  exchange_rate_date: '',
  exemption_reason_code: '',
  exemption_reason: '',
  original_invoice: null,
  original_invoice_id: '',
  // Fields this screen does not show. A save has to send them back.
  line_withholding: { 'line-1': '601' },
  tax_total_convention: '',
  customization_id: 'TR1.2.1',
  amount_in_words: false,
  notes: ['Printed on the invoice'],
};

/** The integrator numbers the document: worth a word, never a refusal. */
const NO_NUMBER: EInvoiceViolation = {
  rule_id: 'TR-ID-01',
  severity: 'warning',
  message: 'The invoice has no e-Fatura document ID, so the file is written with an empty ID.',
  term: 'ID',
  params: {},
};

/** No scenario chosen: the file cannot be written. */
const NO_SCENARIO: EInvoiceViolation = {
  rule_id: 'TR-PROFILE-01',
  severity: 'fatal',
  message: "The scenario '' is not one GİB defines.",
  term: 'ProfileID',
  params: { profile: '' },
};

function trRun(over: Partial<EInvoiceDryRun> = {}): EInvoiceDryRun {
  return {
    format: 'ubl_tr',
    valid: true,
    violations: [NO_NUMBER],
    document: {
      uuid: '0b6f0c1e-2f5a-5d0e-9c55-1c2d3e4f5a6b',
      document_id: '',
      profile_id: 'TICARIFATURA',
      invoice_type: 'TEVKIFAT',
      currency: 'TRY',
      line_extension: '1000.00',
      tax_inclusive: '1200.00',
      payable: '1120.00',
      inferred: { invoice_type: 'TEVKIFAT' },
      signed: false,
    },
    tax_source: {
      source_kind: 'invoice',
      source_id: INVOICE_ID,
      project_id: 'proj-1',
      country_code: 'TR',
      currency_code: 'TRY',
      status: 'confirmed',
      net_amount: '1000.00',
      vat_rate_pct: '20',
    },
    fields: FIELDS,
    ...over,
  };
}

interface Server {
  offeredFirst: string | null;
  fields: TrEInvoiceFields;
  metadata: Record<string, unknown>;
  run: EInvoiceDryRun;
}

let server: Server;

/** Route apiGet by URL, so each of the four reads gets its own answer. */
function respond(over: Partial<Server> = {}) {
  server = { offeredFirst: 'ubl_tr', fields: FIELDS, metadata: {}, run: trRun(), ...over };
  apiGetMock.mockImplementation((url: string) => {
    if (url.includes('einvoice-profiles')) {
      return Promise.resolve({ default: server.offeredFirst, profiles: REGISTRY });
    }
    if (url.endsWith('/einvoice/tr')) {
      return Promise.resolve({
        invoice_id: INVOICE_ID,
        uuid: '0b6f0c1e-2f5a-5d0e-9c55-1c2d3e4f5a6b',
        fields: server.fields,
        unreadable: '',
        tax_source: { source_kind: 'invoice', source_id: INVOICE_ID, project_id: 'proj-1' },
        line_ids: ['line-1'],
      });
    }
    if (url.includes('dry_run=true')) {
      const asked = /format=([^&]+)/.exec(url)?.[1] ?? '';
      return Promise.resolve(
        asked === 'ubl_tr' ? server.run : { format: asked, valid: true, violations: [] },
      );
    }
    return Promise.resolve({ id: INVOICE_ID, metadata: server.metadata });
  });
  // The save answers with what it stored, and the next read returns it.
  apiPutMock.mockImplementation((_url: string, body?: unknown) => {
    server.fields = body as TrEInvoiceFields;
    return Promise.resolve({ invoice_id: INVOICE_ID, uuid: 'x', fields: server.fields });
  });
  apiPatchMock.mockImplementation((_url: string, body?: unknown) => {
    server.metadata = (body as { metadata: Record<string, unknown> }).metadata;
    return Promise.resolve({ id: INVOICE_ID, metadata: server.metadata });
  });
}

function renderModal() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <EInvoiceModal
        open
        onClose={vi.fn()}
        invoiceId={INVOICE_ID}
        invoiceNumber="FTR-2026-77"
        returnCandidates={[{ id: 'inv-0', invoice_number: 'FTR-2026-12' }]}
      />
    </QueryClientProvider>,
  );
}

function picker(): HTMLSelectElement {
  return screen.getByRole('combobox', { name: 'finance.einvoice.profile' }) as HTMLSelectElement;
}

function downloadButton(): HTMLButtonElement {
  return screen.getByText('einvoice.tr.download').closest('button')!;
}

function dryRunCalls(format: string): number {
  return apiGetMock.mock.calls.filter(
    ([url]) => url.includes('dry_run=true') && url.includes(`format=${format}`),
  ).length;
}

/** The Turkish section with its stored values in, and the first report on screen. */
async function ready(): Promise<HTMLSelectElement> {
  const scenario = (await screen.findByLabelText('einvoice.tr.fields.profile_id')) as HTMLSelectElement;
  await waitFor(() => expect(scenario).not.toBeDisabled());
  await screen.findByText('einvoice.tr.figures.title');
  return scenario;
}

describe('EInvoiceModal, UBL-TR', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('the format picker', () => {
    it('offers the national format first, selected, for a seller the registry names one for', async () => {
      respond();
      renderModal();
      await ready();

      const options = within(picker()).getAllByRole('option') as HTMLOptionElement[];
      expect(options.map((o) => o.value)).toEqual(['ubl_tr', 'xrechnung', 'peppol']);
      expect(picker().value).toBe('ubl_tr');
      // A German profile was never checked on the way there.
      expect(dryRunCalls('xrechnung')).toBe(0);
    });

    it('keeps the registry order and its own default when no format is offered first', async () => {
      respond({ offeredFirst: null });
      renderModal();

      await waitFor(() => expect(within(picker()).getAllByRole('option')).toHaveLength(3));
      const options = within(picker()).getAllByRole('option') as HTMLOptionElement[];
      expect(options.map((o) => o.value)).toEqual(['xrechnung', 'peppol', 'ubl_tr']);
      expect(picker().value).toBe('xrechnung');
      expect(dryRunCalls('ubl_tr')).toBe(0);
    });
  });

  describe('the Turkish section', () => {
    it('is shown for the Turkish format and for no other', async () => {
      respond();
      renderModal();
      await ready();

      expect(screen.getByText('einvoice.tr.fields.title')).toBeInTheDocument();
      expect(screen.getByText('einvoice.tr.unsigned_notice')).toBeInTheDocument();

      fireEvent.change(picker(), { target: { value: 'xrechnung' } });

      await waitFor(() => expect(screen.queryByText('einvoice.tr.fields.title')).toBeNull());
      expect(screen.queryByText('einvoice.tr.unsigned_notice')).toBeNull();
      expect(screen.queryByText('einvoice.tr.figures.title')).toBeNull();
      // The EN 16931 download is back under its own name.
      expect(screen.getByText('finance.einvoice.downloadXml')).toBeInTheDocument();
    });

    it('does not appear at all for a seller the registry offers nothing national', async () => {
      respond({ offeredFirst: null });
      renderModal();

      await screen.findByText('finance.einvoice.compliant');
      expect(screen.queryByText('einvoice.tr.fields.title')).toBeNull();
      expect(apiGetMock.mock.calls.some(([url]) => url.endsWith('/einvoice/tr'))).toBe(false);
    });

    it('asks for an exchange rate only on a foreign currency invoice', async () => {
      respond();
      const lira = renderModal();
      await ready();
      expect(screen.queryByLabelText('einvoice.tr.fields.exchange_rate')).toBeNull();
      lira.unmount();

      const base = trRun();
      respond({
        run: trRun({
          document: { ...base.document!, currency: 'EUR' },
          tax_source: { ...base.tax_source!, currency_code: 'EUR' },
        }),
      });
      renderModal();
      await ready();
      expect(screen.getByLabelText('einvoice.tr.fields.exchange_rate')).toBeInTheDocument();
      expect(screen.getByLabelText('einvoice.tr.fields.exchange_rate_date')).toBeInTheDocument();
    });

    it('offers the original invoice once the type is a return', async () => {
      respond();
      renderModal();
      await ready();
      expect(screen.queryByLabelText('einvoice.tr.fields.original_invoice_id')).toBeNull();

      fireEvent.change(screen.getByLabelText('einvoice.tr.fields.invoice_type'), { target: { value: 'IADE' } });

      const original = screen.getByLabelText('einvoice.tr.fields.original_invoice_id');
      expect(within(original).getByText('FTR-2026-12')).toBeInTheDocument();
      expect(screen.getByLabelText('einvoice.tr.fields.original_invoice_document_id')).toBeInTheDocument();
    });

    it('names a mistyped invoice number beside its field and holds the check back', async () => {
      respond();
      renderModal();
      await ready();

      fireEvent.change(screen.getByLabelText('einvoice.tr.fields.document_id'), { target: { value: 'ABC-1' } });

      expect(screen.getByText('einvoice.tr.error.document_id_format')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'einvoice.tr.save_and_check' })).toBeDisabled();
      expect(apiPutMock).not.toHaveBeenCalled();
    });
  });

  describe('the check', () => {
    it('blocks the download and says why while an error stands', async () => {
      respond({ run: trRun({ valid: false, violations: [NO_SCENARIO, NO_NUMBER] }) });
      renderModal();
      await ready();

      await screen.findByText('finance.einvoice.blockingTitle');
      expect(screen.getByText('TR-PROFILE-01')).toBeInTheDocument();
      // The warning beside it is still listed, in its own group.
      expect(screen.getByText('finance.einvoice.advisoryTitle')).toBeInTheDocument();
      expect(screen.getByText('TR-ID-01')).toBeInTheDocument();
      expect(downloadButton()).toBeDisabled();
      expect(screen.getByText('einvoice.tr.blocked_errors')).toBeInTheDocument();
    });

    it('leaves the download open when the only finding is a warning', async () => {
      respond();
      renderModal();
      await ready();

      await screen.findByText('TR-ID-01');
      expect(screen.queryByText('finance.einvoice.blockingTitle')).toBeNull();
      expect(downloadButton()).not.toBeDisabled();
      expect(screen.queryByText('einvoice.tr.blocked_errors')).toBeNull();
      expect(screen.queryByText('einvoice.tr.blocked_unsaved')).toBeNull();
    });

    it('lists a finding that asks for nothing apart from the warnings', async () => {
      const NOTE: EInvoiceViolation = {
        rule_id: 'OCE-TR-02',
        severity: 'info',
        message: 'Stamp duty of group 20 is not decided yet. It is not printed on the invoice.',
        term: 'TaxSubtotal[20]',
        params: { group: '20', figure: 'Stamp duty', reason: 'not chosen' },
      };
      respond({ run: trRun({ violations: [NOTE] }) });
      renderModal();
      await ready();

      await screen.findByText('einvoice.tr.info_title');
      expect(screen.getByText('OCE-TR-02')).toBeInTheDocument();
      expect(screen.queryByText('finance.einvoice.advisoryTitle')).toBeNull();
      expect(downloadButton()).not.toBeDisabled();
    });

    it('jumps to the field a finding names', async () => {
      respond({ run: trRun({ valid: false, violations: [NO_SCENARIO, NO_NUMBER] }) });
      renderModal();
      const scenario = await ready();

      const row = (await screen.findByText('TR-PROFILE-01')).closest('li')!;
      fireEvent.click(within(row).getByText('einvoice.tr.go_to_field'));
      expect(document.activeElement).toBe(scenario);

      const warning = screen.getByText('TR-ID-01').closest('li')!;
      fireEvent.click(within(warning).getByText('einvoice.tr.go_to_field'));
      expect(document.activeElement).toBe(screen.getByLabelText('einvoice.tr.fields.document_id'));
    });

    it('offers no jump for a finding fixed on another screen', async () => {
      const UNCONFIRMED: EInvoiceViolation = {
        rule_id: 'OCE-TR-22',
        severity: 'fatal',
        message: 'The taxes of this invoice are draft, not confirmed.',
        term: 'TaxTotal',
        params: { status: 'draft' },
      };
      respond({ run: trRun({ valid: false, violations: [UNCONFIRMED] }) });
      renderModal();
      await ready();

      const row = (await screen.findByText('OCE-TR-22')).closest('li')!;
      expect(within(row).queryByText('einvoice.tr.go_to_field')).toBeNull();
    });

    it('holds the download while typed fields are not saved, then saves the whole block and checks again', async () => {
      respond();
      renderModal();
      const scenario = await ready();
      await waitFor(() => expect(downloadButton()).not.toBeDisabled());
      const checksBefore = dryRunCalls('ubl_tr');

      fireEvent.change(scenario, { target: { value: 'TICARIFATURA' } });

      // The verdict on screen is about the stored fields, not the typed ones.
      expect(downloadButton()).toBeDisabled();
      expect(screen.getByText('einvoice.tr.blocked_unsaved')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'einvoice.tr.save_and_check' }));

      await waitFor(() => expect(apiPutMock).toHaveBeenCalledTimes(1));
      const [url, body] = apiPutMock.mock.calls[0]!;
      expect(url).toContain(`/finance/invoices/${INVOICE_ID}/einvoice/tr`);
      expect(body).toMatchObject({
        profile_id: 'TICARIFATURA',
        original_invoice: null,
        // Not on screen, and still there after the save.
        line_withholding: { 'line-1': '601' },
        customization_id: 'TR1.2.1',
        amount_in_words: false,
        notes: ['Printed on the invoice'],
      });
      // Party details were not touched, so the invoice itself is not written.
      expect(apiPatchMock).not.toHaveBeenCalled();

      await waitFor(() => expect(dryRunCalls('ubl_tr')).toBeGreaterThan(checksBefore));
      await waitFor(() => expect(downloadButton()).not.toBeDisabled());
      expect(screen.queryByText('einvoice.tr.blocked_unsaved')).toBeNull();
    });

    it('runs the report again without writing when nothing was typed', async () => {
      respond();
      renderModal();
      await ready();
      await waitFor(() => expect(downloadButton()).not.toBeDisabled());
      const checksBefore = dryRunCalls('ubl_tr');

      fireEvent.click(screen.getByRole('button', { name: 'einvoice.tr.check' }));

      await waitFor(() => expect(dryRunCalls('ubl_tr')).toBeGreaterThan(checksBefore));
      expect(apiPutMock).not.toHaveBeenCalled();
      expect(apiPatchMock).not.toHaveBeenCalled();
    });

    it('shows what the server said about a refused field and does not unlock the download', async () => {
      respond();
      apiPutMock.mockRejectedValue(
        new api.ApiError(422, 'Unprocessable Content', {
          detail: "exemption_reason_code '999' is not in the published exemption code list",
        }),
      );
      renderModal();
      await ready();

      fireEvent.change(screen.getByLabelText('einvoice.tr.fields.exemption_reason_code'), {
        target: { value: '999' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'einvoice.tr.save_and_check' }));

      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toContain('published exemption code list');
      expect(downloadButton()).toBeDisabled();
    });

    it('writes a party detail into the invoice metadata and keeps the rest of it', async () => {
      respond({
        metadata: { po_id: 'po-7', einvoice: { buyer_reference: 'L-1', seller: { name: 'Kept as it was' } } },
      });
      renderModal();
      await ready();

      fireEvent.change(screen.getByLabelText('einvoice.tr.parties.seller_tax_office'), {
        target: { value: 'Central tax office' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'einvoice.tr.save_and_check' }));

      await waitFor(() => expect(apiPatchMock).toHaveBeenCalledTimes(1));
      const [url, body] = apiPatchMock.mock.calls[0]!;
      expect(url).toBe(`/v1/finance/${INVOICE_ID}`);
      expect(body).toEqual({
        metadata: {
          po_id: 'po-7',
          einvoice: {
            buyer_reference: 'L-1',
            seller: { name: 'Kept as it was', tax_office: 'Central tax office' },
          },
        },
      });
      // The Turkish block was not typed in, so it is not rewritten.
      expect(apiPutMock).not.toHaveBeenCalled();
    });
  });

  describe('the amounts', () => {
    it('prints the figures as the server sent them, in TL', async () => {
      respond();
      renderModal();
      await ready();

      // The mock renders the unit's key; the amount in front of it is the
      // server's string, digit for digit, with nothing added or rounded.
      // Twice: the line total, and the amount the stored taxes were computed on.
      expect(screen.getAllByText('1000.00 einvoice.tr.currency_tl')).toHaveLength(2);
      expect(screen.getByText('1200.00 einvoice.tr.currency_tl')).toBeInTheDocument();
      expect(screen.getByText('1120.00 einvoice.tr.currency_tl')).toBeInTheDocument();
      expect(screen.getByText('20 %')).toBeInTheDocument();
      expect(screen.getByText('einvoice.tr.tax_source.confirmed')).toBeInTheDocument();
      // A type nobody typed is marked as derived.
      expect(screen.getByText('einvoice.tr.figures.inferred')).toBeInTheDocument();
      // An ordinary invoice is taxed on its own figures.
      expect(screen.queryByText('einvoice.tr.figures.from_certificate')).toBeNull();
    });

    it('says the figures come from the payment certificate when the invoice was raised from one', async () => {
      const base = trRun();
      respond({ run: trRun({ tax_source: { ...base.tax_source!, source_kind: 'progress_claim' } }) });
      renderModal();
      await ready();

      expect(screen.getByText('einvoice.tr.figures.from_certificate')).toBeInTheDocument();
    });
  });

  describe('the download', () => {
    it('asks for the Turkish file and leaves the name to the server', async () => {
      respond();
      renderModal();
      await ready();
      await waitFor(() => expect(downloadButton()).not.toBeDisabled());

      fireEvent.click(downloadButton());

      await waitFor(() => expect(downloadMock).toHaveBeenCalledTimes(1));
      const [url, fallback] = downloadMock.mock.calls[0]!;
      expect(url).toContain(`/finance/invoices/${INVOICE_ID}/einvoice?format=ubl_tr`);
      expect(url).toContain('embed=false');
      // Used only when the response carries no file name of its own.
      expect(fallback).toBe('einvoice_FTR-2026-77_ubl_tr.xml');
      // There is no hybrid PDF of an e-Fatura.
      expect(screen.queryByText('finance.einvoice.downloadPdf')).toBeNull();
    });

    it('shows the server message when the file is refused', async () => {
      respond();
      downloadMock.mockRejectedValueOnce(
        new Error('invoice cannot be written as an e-Fatura yet: TR-PROFILE-01'),
      );
      renderModal();
      await ready();
      await waitFor(() => expect(downloadButton()).not.toBeDisabled());

      fireEvent.click(downloadButton());

      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toContain('TR-PROFILE-01');
    });
  });
});
