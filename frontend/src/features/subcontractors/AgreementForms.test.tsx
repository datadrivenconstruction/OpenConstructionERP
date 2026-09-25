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
    await waitFor(() => expect(onClose).toHaveBeenCalled());
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
