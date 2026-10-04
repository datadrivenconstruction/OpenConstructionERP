// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the agreement and payment application forms.
//
// One scenario: a 120,000 EUR agreement at 5% retention, and a first payment
// application at 30% of it, 36,000 gross.
//
//   * the agreement goes out with the value and retention typed, for the
//     subcontractor the page is open on;
//   * left untouched, the retention shows the country's usual figure and is
//     not sent, so the server applies and records it as the default;
//   * a number field selects its value on focus, so typing replaces the
//     prefilled 5 instead of appending to it (5 then 5 used to read 55);
//   * the payment application shows the retention and net the server will
//     book before it is sent, and sends the gross;
//   * a refusal from the payment gate reads as sentences, not codes;
//   * a draft agreement offers Sign, a signed one does not.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  createAgreement: vi.fn(),
  submitPaymentApplication: vi.fn(),
  updateAgreement: vi.fn(),
}));

vi.mock('@/features/contracts/api', () => ({
  listContracts: vi.fn().mockResolvedValue({
    items: [
      {
        id: 'ct-9',
        code: 'SC-009',
        title: 'Drywall subcontract',
        total_value: '120000.00',
        currency: 'EUR',
        retention_percent: '5.00',
        counterparty_type: 'subcontractor',
      },
    ],
    total: 1,
  }),
  // The project sits in Great Britain, where a subcontract usually holds 3%.
  getContractCountryDefaults: vi.fn().mockResolvedValue({
    project_id: 'prj-1',
    country_code: 'GB',
    has_defaults: true,
    standard_form: null,
    values: { retention_percent: '3' },
    sources: { retention_percent: { source: 'standard_form', reference: 'JCT', note: '' } },
    release_split_source: 'table',
  }),
}));

vi.mock('@/features/projects/api', () => ({
  projectsApi: {
    list: vi.fn().mockResolvedValue([{ id: 'prj-1', name: 'Zagreb, block B', currency: 'EUR' }]),
  },
}));

const addToast = vi.fn();
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof addToast }) => unknown) => sel({ addToast }),
}));

import * as api from './api';
import type { Agreement } from './api';
import * as contractsApi from '@/features/contracts/api';
import { ApiError } from '@/shared/lib/api';
import { AgreementFormModal, PaymentApplicationFormModal, SignAgreementButton } from './AgreementForms';

// No i18n resources are loaded here: a label renders as its key, or as its
// defaultValue where the call gives one.

const agreement = {
  id: 'ag-1',
  subcontractor_id: 'sub-1',
  project_id: 'prj-1',
  title: 'Drywall, block B',
  total_value: '120000.00',
  currency: 'EUR',
  retention_percent: '5.00',
  status: 'active',
  requires_lien_waiver: false,
  metadata: {},
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
} as Agreement;

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('AgreementFormModal', () => {
  it('creates the agreement with the value and retention typed', async () => {
    vi.mocked(api.createAgreement).mockResolvedValue(agreement);
    const onClose = vi.fn();
    wrap(<AgreementFormModal subcontractorId="sub-1" onClose={onClose} />);

    await waitFor(() =>
      expect((screen.getByTestId('agreement-project') as HTMLSelectElement).value).toBe('prj-1'),
    );
    fireEvent.change(screen.getByTestId('agreement-title'), { target: { value: 'Drywall, block B' } });
    fireEvent.change(screen.getByTestId('agreement-value'), { target: { value: '120000' } });
    fireEvent.change(screen.getByTestId('agreement-retention'), { target: { value: '5' } });
    fireEvent.click(screen.getByText('Create'));

    await waitFor(() => expect(api.createAgreement).toHaveBeenCalled());
    expect(api.createAgreement).toHaveBeenCalledWith(
      expect.objectContaining({
        subcontractor_id: 'sub-1',
        project_id: 'prj-1',
        title: 'Drywall, block B',
        total_value: '120000',
        currency: 'EUR',
        retention_percent: '5',
      }),
    );
    expect(vi.mocked(api.createAgreement).mock.calls[0]?.[0]?.contract_id).toBeUndefined();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('links the same subcontract from contracts and takes its figures', async () => {
    vi.mocked(api.createAgreement).mockResolvedValue(agreement);
    wrap(<AgreementFormModal subcontractorId="sub-1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('SC-009 Drywall subcontract')).toBeTruthy());
    fireEvent.change(screen.getByTestId('agreement-contract'), { target: { value: 'ct-9' } });
    expect((screen.getByTestId('agreement-title') as HTMLInputElement).value).toBe('Drywall subcontract');
    expect((screen.getByTestId('agreement-value') as HTMLInputElement).value).toBe('120000.00');
    fireEvent.click(screen.getByText('Create'));

    await waitFor(() =>
      expect(api.createAgreement).toHaveBeenCalledWith(
        expect.objectContaining({ contract_id: 'ct-9', total_value: '120000', retention_percent: '5' }),
      ),
    );
  });

  it("shows the country's usual retention and leaves it to the server when untouched", async () => {
    vi.mocked(api.createAgreement).mockResolvedValue(agreement);
    wrap(<AgreementFormModal subcontractorId="sub-1" onClose={vi.fn()} />);

    await waitFor(() =>
      expect((screen.getByTestId('agreement-retention') as HTMLInputElement).value).toBe('3'),
    );
    expect(screen.getByTestId('default-hint-retention_percent').textContent).toContain('United Kingdom');
    fireEvent.change(screen.getByTestId('agreement-title'), { target: { value: 'Drywall, block B' } });
    fireEvent.change(screen.getByTestId('agreement-value'), { target: { value: '120000' } });
    fireEvent.click(screen.getByText('Create'));

    await waitFor(() => expect(api.createAgreement).toHaveBeenCalled());
    // Not a 5 the form made up, and not the 3 either: the server applies the
    // country's figure and records it as a default rather than as typed.
    expect(vi.mocked(api.createAgreement).mock.calls[0]?.[0]?.retention_percent).toBeUndefined();
  });

  it('starts a Gulf agreement from the FIDIC limit, not the rate the limit stops', async () => {
    // FIDIC: 10% of each payment until 5% of the sum is held. An agreement
    // holds every payment at one rate with no ceiling, so the server starts it
    // from 5% and the form must show that, with the limit's own reference.
    vi.mocked(contractsApi.getContractCountryDefaults).mockResolvedValueOnce({
      project_id: 'prj-1',
      country_code: 'AE',
      has_defaults: true,
      standard_form: 'FIDIC Red Book 2017',
      values: { retention_percent: '10', retention_cap_percent: '5' },
      sources: {
        retention_percent: { source: 'standard_form', reference: 'Sub-Clause 14.3(iii)', note: '' },
        retention_cap_percent: {
          source: 'standard_form',
          reference: 'Limit of Retention Money',
          note: '',
        },
      },
      release_split_source: 'table',
      subcontract_retention_percent: '5',
      subcontract_retention_from: 'retention_cap_percent',
    });
    vi.mocked(api.createAgreement).mockResolvedValue(agreement);
    wrap(<AgreementFormModal subcontractorId="sub-1" onClose={vi.fn()} />);

    await waitFor(() =>
      expect((screen.getByTestId('agreement-retention') as HTMLInputElement).value).toBe('5'),
    );
    const hint = screen.getByTestId('default-hint-retention_percent');
    expect(hint.textContent).toContain('Limit of Retention Money');
    expect(hint.textContent).not.toContain('14.3(iii)');
    fireEvent.change(screen.getByTestId('agreement-title'), { target: { value: 'MEP, tower 2' } });
    fireEvent.change(screen.getByTestId('agreement-value'), { target: { value: '1000000' } });
    fireEvent.click(screen.getByText('Create'));

    await waitFor(() => expect(api.createAgreement).toHaveBeenCalled());
    // Still left to the server, which applies and stamps the same 5.
    expect(vi.mocked(api.createAgreement).mock.calls[0]?.[0]?.retention_percent).toBeUndefined();
  });

  it('asks for a figure where the country has no usual retention, rather than storing 5%', async () => {
    // An Italian project: the table has no row, so a blank would reach the
    // server as "not sent" and be stored at the platform's 5% fallback.
    vi.mocked(contractsApi.getContractCountryDefaults).mockResolvedValueOnce({
      project_id: 'prj-1',
      country_code: 'IT',
      has_defaults: false,
      standard_form: null,
      values: {},
      sources: {},
      release_split_source: null,
    });
    vi.mocked(api.createAgreement).mockResolvedValue(agreement);
    wrap(<AgreementFormModal subcontractorId="sub-1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByTestId('agreement-retention-required')).toBeTruthy());
    expect((screen.getByTestId('agreement-retention') as HTMLInputElement).value).toBe('');
    fireEvent.change(screen.getByTestId('agreement-title'), { target: { value: 'Drywall, block B' } });
    fireEvent.change(screen.getByTestId('agreement-value'), { target: { value: '120000' } });
    fireEvent.click(screen.getByText('Create'));
    expect(api.createAgreement).not.toHaveBeenCalled();

    // Zero is an answer: no retention on this agreement.
    fireEvent.change(screen.getByTestId('agreement-retention'), { target: { value: '0' } });
    expect(screen.queryByTestId('agreement-retention-required')).toBeNull();
    fireEvent.click(screen.getByText('Create'));
    await waitFor(() => expect(api.createAgreement).toHaveBeenCalled());
    expect(vi.mocked(api.createAgreement).mock.calls[0]?.[0]?.retention_percent).toBe('0');
  });

  it("holds a linked contract's rate to the cap that contract states", async () => {
    vi.mocked(contractsApi.listContracts).mockResolvedValueOnce({
      items: [
        {
          id: 'ct-ae',
          code: 'SC-AE',
          title: 'MEP subcontract',
          total_value: '1000000.00',
          currency: 'AED',
          retention_percent: '10.00',
          counterparty_type: 'subcontractor',
          terms: { payment_terms: { retention_cap_percent: '5' } },
        },
      ],
      total: 1,
    } as unknown as Awaited<ReturnType<typeof contractsApi.listContracts>>);
    vi.mocked(api.createAgreement).mockResolvedValue(agreement);
    wrap(<AgreementFormModal subcontractorId="sub-1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('SC-AE MEP subcontract')).toBeTruthy());
    fireEvent.change(screen.getByTestId('agreement-contract'), { target: { value: 'ct-ae' } });
    // The contract holds 10% until its 5% cap; the agreement has no cap, so 5%.
    expect((screen.getByTestId('agreement-retention') as HTMLInputElement).value).toBe('5');
    fireEvent.click(screen.getByText('Create'));

    await waitFor(() =>
      expect(api.createAgreement).toHaveBeenCalledWith(
        expect.objectContaining({ contract_id: 'ct-ae', retention_percent: '5' }),
      ),
    );
  });

  it('selects the prefilled retention on focus so typing replaces it', () => {
    wrap(<AgreementFormModal subcontractorId="sub-1" onClose={vi.fn()} />);
    const input = screen.getByTestId('agreement-retention') as HTMLInputElement;
    const select = vi.spyOn(input, 'select');
    fireEvent.focus(input);
    expect(select).toHaveBeenCalled();
  });
});

describe('PaymentApplicationFormModal', () => {
  it('shows the retention and net before sending the gross', async () => {
    vi.mocked(api.submitPaymentApplication).mockResolvedValue({} as never);
    wrap(<PaymentApplicationFormModal agreement={agreement} onClose={vi.fn()} />);

    fireEvent.change(screen.getByTestId('pay-app-gross'), { target: { value: '36000' } });
    const preview = screen.getByTestId('pay-app-preview');
    expect(preview.textContent).toMatch(/1\D?800/);
    expect(preview.textContent).toMatch(/34\D?200/);

    fireEvent.click(screen.getByText('subcontractors.submit_pay_app'));
    await waitFor(() =>
      expect(api.submitPaymentApplication).toHaveBeenCalledWith(
        expect.objectContaining({ agreement_id: 'ag-1', gross_amount: '36000', currency: 'EUR' }),
      ),
    );
  });

  it('reads a payment gate refusal as sentences', async () => {
    vi.mocked(api.submitPaymentApplication).mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: { code: 'payment_blocked', reasons: ['missing_required_certificate:insurance'] },
      }),
    );
    wrap(<PaymentApplicationFormModal agreement={agreement} onClose={vi.fn()} />);
    fireEvent.change(screen.getByTestId('pay-app-gross'), { target: { value: '36000' } });
    fireEvent.click(screen.getByText('subcontractors.submit_pay_app'));

    await waitFor(() => expect(addToast).toHaveBeenCalled());
    const title = String(addToast.mock.calls[0]?.[0]?.title);
    expect(title).toBe('subcontractors.reason_code.missing_certificate');
    expect(title).not.toContain(':');
  });
});

describe('SignAgreementButton', () => {
  it('signs a draft agreement', async () => {
    vi.mocked(api.updateAgreement).mockResolvedValue(agreement);
    wrap(<SignAgreementButton agreement={{ ...agreement, status: 'draft' }} />);
    fireEvent.click(screen.getByText('subcontractors.sign_agreement'));
    await waitFor(() => expect(api.updateAgreement).toHaveBeenCalledWith('ag-1', { status: 'active' }));
  });

  it('offers nothing on a signed agreement', () => {
    wrap(<SignAgreementButton agreement={agreement} />);
    expect(screen.queryByText('subcontractors.sign_agreement')).toBeNull();
  });
});
