// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../paymentsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../paymentsApi')>();
  return {
    ...actual,
    paymentsApi: {
      ledger: vi.fn(),
      retention: vi.fn(),
      findings: vi.fn(),
      terms: vi.fn(),
      putTerms: vi.fn(),
      updateInvoice: vi.fn(),
      release: vi.fn(),
      reopen: vi.fn(),
      postRetention: vi.fn(),
      voidPosting: vi.fn(),
    },
  };
});

import { paymentsApi, type LedgerInvoice, type ProjectLedger, type ReleaseFigures } from '../paymentsApi';
import { PaymentsPanel } from '../PaymentsPanel';

// Invented figures: a cumulative interim invoice of 6000 net, 10 % retention on the gross, rounding to 1000.
const FIGURES: ReleaseFigures = {
  key: 'i-1',
  kind: 'interim',
  net: '6000.00',
  net_deduction: '0.00',
  net_after: '6000.00',
  vat: '1140.00',
  vat_deduction: '0.00',
  vat_after: '1140.00',
  gross: '7140.00',
  gross_deduction: '0.00',
  gross_after: '7140.00',
  previous_releases: '0.00',
  previous_counted: true,
  retention_percent: '10',
  retention_base: '7140.00',
  retention: '714.00',
  retention_source: 'terms',
  release_before_rounding: '6426.00',
  rounding: '426.00',
  release: '6000.00',
  discount_percent: '0',
  discount: '0.00',
  payable: '6000.00',
  due_on: '2026-05-30',
  discount_until: null,
  retention_held_after: '714.00',
};

function invoice(over: Partial<LedgerInvoice> = {}): LedgerInvoice {
  return {
    invoice_id: 'i-1',
    number: 'AR-1',
    invoice_date: '2026-05-01',
    finance_status: 'approved',
    kind: 'interim',
    kind_set: true,
    contract_source: 'release_view',
    release_status: 'open',
    released_at: null,
    net_deduction_note: '',
    gross_deduction_note: '',
    figures: FIGURES,
    computed: FIGURES,
    differs: false,
    counted: true,
    progress_pct: '30',
    paid: '0.00',
    paid_cash: '0.00',
    discount_taken: '0.00',
    open_amount: '6000.00',
    ...over,
  };
}

const TOTALS = {
  contract_value: '20000.00',
  invoiced: '6000.00',
  invoiced_pct: '30',
  released: '6000.00',
  payable: '6000.00',
  paid: '0.00',
  open_amount: '6000.00',
  retention_held: '714.00',
  retention_posted: '0.00',
};

const LEDGER: ProjectLedger = {
  project_id: 'p-1',
  currency: 'EUR',
  contracts: [
    {
      contract_id: 'c-1',
      code: 'SC-01',
      title: 'Facade',
      status: 'active',
      invoice_mode: 'cumulative',
      terms_set: true,
      original_value: '20000.00',
      changes: '0.00',
      current_value: '20000.00',
      changes_pct: null,
      measured: '6200.00',
      measured_pct: '31',
      has_measurement: true,
      invoices: [invoice()],
      totals: TOTALS,
    },
  ],
  other_invoices: [
    {
      invoice_id: 'i-9',
      number: 'X-9',
      invoice_date: '2026-05-03',
      finance_status: 'approved',
      net: '100.00',
      gross: '119.00',
      paid: '0.00',
      purchase_order_id: null,
    },
  ],
  totals: TOTALS,
};

function renderPanel(canRelease = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PaymentsPanel projectId="p-1" currency="EUR" canEdit canRelease={canRelease} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(paymentsApi.ledger).mockResolvedValue(LEDGER);
  vi.mocked(paymentsApi.findings).mockResolvedValue({
    project_id: 'p-1',
    findings: [
      {
        rule_id: 'payment_release.invoiced_within_value',
        rule_number: 'V16',
        severity: 'warning',
        message: 'SC-01 is invoiced above what is measured.',
        suggestion: 'Check the measurement.',
        element_ref: 'c-1',
        problem: 'invoiced_over_measured',
      },
    ],
    errors: 0,
    warnings: 1,
  });
  vi.mocked(paymentsApi.retention).mockResolvedValue({
    project_id: 'p-1',
    currency: 'EUR',
    held: '714.00',
    posted: '0.00',
    contracts: [
      {
        contract_id: 'c-1',
        code: 'SC-01',
        title: 'Facade',
        status: 'active',
        retention_percent: '10',
        retention_release_event: 'substantial_completion',
        warranty_enabled: false,
        warranty_percent: '0',
        warranty_release_event: 'defects_period_end',
        warranty_period_months: null,
        withheld: '714.00',
        posted: '0.00',
        held: '714.00',
        postings: [],
      },
    ],
  });
});

describe('PaymentsPanel', () => {
  it('shows each step from the invoice to the release and confirms it', async () => {
    vi.mocked(paymentsApi.release).mockResolvedValue({
      invoice_id: 'i-1',
      contract_id: 'c-1',
      kind: 'interim',
      status: 'released',
      release_amount: '6000.00',
      payable_amount: '6000.00',
    });
    renderPanel();
    fireEvent.click(await screen.findByTestId('ledger-invoice-AR-1'));
    const steps = await screen.findByTestId('release-steps');
    expect(within(steps).getByTestId('release-steps-retention')).toHaveTextContent(/714/);
    expect(within(steps).getByTestId('release-steps-rounding')).toHaveTextContent(/426/);
    expect(within(steps).getByTestId('release-steps-release')).toHaveTextContent(/6[,.\s\u00a0\u202f]?000/);
    // No discount agreed: no discount step.
    expect(within(steps).queryByTestId('release-steps-discount')).toBeNull();
    fireEvent.click(screen.getByTestId('release-confirm'));
    await waitFor(() => expect(paymentsApi.release).toHaveBeenCalledWith('i-1'));
  });

  it('hides the confirm button from a role that cannot release', async () => {
    renderPanel(false);
    fireEvent.click(await screen.findByTestId('ledger-invoice-AR-1'));
    await screen.findByTestId('release-steps');
    expect(screen.queryByTestId('release-confirm')).toBeNull();
    expect(screen.getByText(/A manager confirms releases/)).toBeInTheDocument();
  });

  it('puts an invoice on no contract onto a contract', async () => {
    vi.mocked(paymentsApi.updateInvoice).mockResolvedValue({
      invoice_id: 'i-9',
      contract_id: 'c-1',
      kind: 'interim',
      status: 'open',
      release_amount: null,
      payable_amount: null,
    });
    renderPanel();
    const other = await screen.findByTestId('ledger-other-invoices');
    fireEvent.change(within(other).getByRole('combobox'), { target: { value: 'c-1' } });
    await waitFor(() => expect(paymentsApi.updateInvoice).toHaveBeenCalledWith('i-9', { contract_id: 'c-1' }));
  });

  it('pays held retention back from the register', async () => {
    vi.mocked(paymentsApi.postRetention).mockResolvedValue({
      id: 'r-1',
      contract_id: 'c-1',
      retention_kind: 'interim',
      event: 'substantial_completion',
      event_on: null,
      amount: '714.00',
      posted_on: '2026-10-18',
      status: 'posted',
      document_ref: '',
      note: '',
    });
    renderPanel();
    fireEvent.click(await screen.findByTestId('payments-tab-retention'));
    fireEvent.click(await screen.findByTestId('posting-open-SC-01'));
    expect(screen.getByTestId('posting-amount')).toHaveValue('714.00');
    fireEvent.click(screen.getByTestId('posting-save'));
    await waitFor(() =>
      expect(paymentsApi.postRetention).toHaveBeenCalledWith(
        'c-1',
        expect.objectContaining({ amount: '714.00', event: 'substantial_completion', retention_kind: 'interim' }),
      ),
    );
  });

  it('shows release figures to the cent, so the steps add up on screen', async () => {
    const cents: ReleaseFigures = {
      ...FIGURES,
      net: '138765.43',
      net_after: '138765.43',
      vat: '26365.43',
      vat_after: '26365.43',
      gross: '165130.86',
      gross_after: '165130.86',
      retention: '7632.10',
      release_before_rounding: '82698.76',
      rounding: '98.76',
      release: '82600.00',
    };
    vi.mocked(paymentsApi.ledger).mockResolvedValue({
      ...LEDGER,
      contracts: [{ ...LEDGER.contracts[0]!, invoices: [invoice({ figures: cents, computed: cents })] }],
    });
    renderPanel();
    fireEvent.click(await screen.findByTestId('ledger-invoice-AR-1'));
    const steps = await screen.findByTestId('release-steps');
    // Rounded to whole euros these read 138,765 + 26,365 = 165,131, which does not add up.
    expect(within(steps).getByTestId('release-steps-net')).toHaveTextContent(/138[,.\s]?765[.,]43/);
    expect(within(steps).getByTestId('release-steps-vat')).toHaveTextContent(/26[,.\s]?365[.,]43/);
    expect(within(steps).getByTestId('release-steps-rounding')).toHaveTextContent(/98[.,]76/);
  });

  it('sends deductions typed with a decimal comma as dot-decimal strings', async () => {
    vi.mocked(paymentsApi.updateInvoice).mockResolvedValue({
      invoice_id: 'i-1',
      contract_id: 'c-1',
      kind: 'interim',
      status: 'open',
      release_amount: null,
      payable_amount: null,
    });
    renderPanel();
    fireEvent.click(await screen.findByTestId('ledger-invoice-AR-1'));
    fireEvent.change(await screen.findByTestId('release-net-deduction'), { target: { value: '1.250,50 €' } });
    fireEvent.click(screen.getByTestId('release-save'));
    await waitFor(() =>
      expect(paymentsApi.updateInvoice).toHaveBeenCalledWith('i-1', expect.objectContaining({ net_deduction: '1250.50' })),
    );
  });

  it('lists the checks with their rule number', async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId('payments-tab-checks'));
    const list = await screen.findByTestId('payment-checks');
    expect(list).toHaveTextContent('SC-01 is invoiced above what is measured.');
    expect(list).toHaveTextContent('V16');
  });
});
