// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for <PaymentApprovalActions>.
//
// What is worth pinning:
//
//   * each status offers exactly its next step and calls that step's route;
//   * finance approval goes out only from the lines dialog, with the amount
//     confirmed on each line, never above its claim;
//   * the lines stay readable to anyone who sees the row, with what was not
//     approved shown per line;
//   * a role the backend would refuse is not offered the step at all, and a
//     viewer is offered nothing;
//   * finance approval is held back, with the reason on the button, while the
//     release check says the lien waiver is missing, and a refusal on that
//     ground reads in the page's words;
//   * reject cannot go out without a reason, and carries the one typed;
//   * a paid or rejected pay application offers nothing but its lines;
//   * the dialog ends on what is payable: the claimed gross less what was
//     not approved, less retention at the agreement's rate, and the list
//     shows that figure with the claim beneath it once they differ.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  approvePaymentForeman: vi.fn(),
  approvePaymentFinance: vi.fn(),
  markPaymentPaid: vi.fn(),
  rejectPaymentApplication: vi.fn(),
  getPaymentReleaseCheck: vi.fn(),
  listPaymentApplicationLines: vi.fn(),
  listWorkPackages: vi.fn(),
}));

let role: string | null = 'manager';
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (sel: (s: { userRole: string | null }) => unknown) => sel({ userRole: role }),
}));

const addToast = vi.fn();
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof addToast }) => unknown) => sel({ addToast }),
}));

import * as api from './api';
import type { PaymentApplication, PaymentApplicationStatus } from './api';
import { PayAppAmount, PaymentApprovalActions } from './PaymentApprovalActions';
import { ApiError } from '@/shared/lib/api';

const foremanMock = vi.mocked(api.approvePaymentForeman);
const financeMock = vi.mocked(api.approvePaymentFinance);
const paidMock = vi.mocked(api.markPaymentPaid);
const rejectMock = vi.mocked(api.rejectPaymentApplication);
const checkMock = vi.mocked(api.getPaymentReleaseCheck);
const linesMock = vi.mocked(api.listPaymentApplicationLines);
const packagesMock = vi.mocked(api.listWorkPackages);

function payment(status: PaymentApplicationStatus, over: Partial<PaymentApplication> = {}): PaymentApplication {
  return {
    id: 'pa-1',
    agreement_id: 'ag-1',
    application_number: 'PA-1',
    period_start: '2026-04-01',
    period_end: '2026-04-30',
    gross_amount: '2000.00',
    retention_amount: '200.00',
    net_amount: '1800.00',
    currency: 'USD',
    status,
    ...over,
  } as PaymentApplication;
}

function renderActions(
  status: PaymentApplicationStatus,
  requiresWaiver = false,
  extra: { payment?: Partial<PaymentApplication>; retentionPercent?: string } = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PaymentApprovalActions
        payment={payment(status, extra.payment)}
        requiresWaiver={requiresWaiver}
        retentionPercent={extra.retentionPercent}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  role = 'manager';
  checkMock.mockResolvedValue({ payment_application_id: 'pa-1', waiver_required: true, blocked: false, reasons: [] });
  // One line as the portal submits it: claimed, nothing approved yet.
  linesMock.mockResolvedValue([
    {
      id: 'pal-1',
      payment_application_id: 'pa-1',
      work_package_id: 'wp-1',
      claimed_amount: '2000.00',
      certified_amount: '0.00',
      approved_amount: '0.00',
    },
  ]);
  packagesMock.mockResolvedValue([{ id: 'wp-1', name: 'Footings' }] as never);
});

async function openApproval() {
  fireEvent.click(screen.getByTestId('pay-app-approve-payment'));
  return (await screen.findByTestId('pay-app-approved-input')) as HTMLInputElement;
}

describe('PaymentApprovalActions', () => {
  it('offers the payment certificate only where the agreement has a certificate layout', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <PaymentApprovalActions payment={payment('paid')} requiresWaiver={false} />
      </QueryClientProvider>,
    );
    expect(screen.queryByTestId('pay-app-hakedis-open')).toBeNull();
    rerender(
      <QueryClientProvider client={qc}>
        <PaymentApprovalActions payment={payment('paid')} requiresWaiver={false} hakedisAvailable />
      </QueryClientProvider>,
    );
    expect(screen.getByTestId('pay-app-hakedis-open')).toHaveTextContent('Certificate');
    // The lines stay on offer beside it.
    expect(screen.getByTestId('pay-app-lines-open')).toBeInTheDocument();
  });

  it('offers the foreman step on a submitted pay application and calls its route', async () => {
    foremanMock.mockResolvedValue(payment('foreman_approved'));
    renderActions('submitted');
    expect(screen.queryByTestId('pay-app-approve-payment')).toBeNull();
    fireEvent.click(screen.getByTestId('pay-app-approve-work'));
    await waitFor(() => expect(foremanMock).toHaveBeenCalledWith('pa-1'));
  });

  it('approves the payment from the lines, starting each at its claim', async () => {
    financeMock.mockResolvedValue(payment('finance_approved'));
    renderActions('foreman_approved');
    expect(screen.queryByTestId('pay-app-approve-work')).toBeNull();
    const input = await openApproval();
    // Nothing goes out until the person confirms in the dialog.
    expect(financeMock).not.toHaveBeenCalled();
    expect(input.value).toBe('2000.00');
    fireEvent.click(screen.getByTestId('pay-app-approve-confirm'));
    await waitFor(() =>
      expect(financeMock).toHaveBeenCalledWith('pa-1', [{ line_id: 'pal-1', approved_amount: '2000.00' }]),
    );
  });

  it('sends a lowered amount as confirmed, and shows what is not approved', async () => {
    financeMock.mockResolvedValue(payment('finance_approved'));
    renderActions('foreman_approved');
    const input = await openApproval();
    fireEvent.change(input, { target: { value: '1500' } });
    expect(screen.getByTestId('pay-app-line-gap').textContent).toMatch(/500/);
    fireEvent.click(screen.getByTestId('pay-app-approve-confirm'));
    await waitFor(() =>
      expect(financeMock).toHaveBeenCalledWith('pa-1', [{ line_id: 'pal-1', approved_amount: '1500' }]),
    );
  });

  it('will not approve a line above its claim', async () => {
    renderActions('foreman_approved');
    const input = await openApproval();
    fireEvent.change(input, { target: { value: '2000.01' } });
    expect((screen.getByTestId('pay-app-approve-confirm') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Cannot exceed the amount claimed.')).toBeInTheDocument();
    expect(financeMock).not.toHaveBeenCalled();
  });

  it('does not offer an editor the finance step the backend keeps for managers', () => {
    role = 'editor';
    renderActions('foreman_approved');
    expect(screen.queryByTestId('pay-app-approve-payment')).toBeNull();
    // Reject is an editor's step, so it stays.
    expect(screen.getByTestId('pay-app-reject')).toBeInTheDocument();
  });

  it('resolves an alias to its role, so an estimator can approve the work', () => {
    role = 'estimator';
    renderActions('submitted');
    expect(screen.getByTestId('pay-app-approve-work')).toBeInTheDocument();
  });

  it('offers a viewer no step, only the lines to read', () => {
    role = 'viewer';
    renderActions('submitted');
    expect(screen.queryByTestId('pay-app-approve-work')).toBeNull();
    expect(screen.queryByTestId('pay-app-reject')).toBeNull();
    expect(screen.getByTestId('pay-app-lines-open')).toBeInTheDocument();
  });

  it('holds finance approval while the waiver is missing, and says why', async () => {
    checkMock.mockResolvedValue({
      payment_application_id: 'pa-1',
      waiver_required: true,
      blocked: true,
      reasons: ['missing_waiver'],
    });
    renderActions('foreman_approved', true);
    const button = screen.getByTestId('pay-app-approve-payment') as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(button.title).toBe('A signed lien waiver covering the net amount must be on file first.');
  });

  it('words a waiver refusal from the server in the page words', async () => {
    financeMock.mockRejectedValue(
      new ApiError(409, 'Conflict', { detail: { code: 'missing_waiver', message: 'server sentence' } }),
    );
    renderActions('foreman_approved');
    await openApproval();
    fireEvent.click(screen.getByTestId('pay-app-approve-confirm'));
    await waitFor(() =>
      expect(addToast).toHaveBeenCalledWith({
        type: 'error',
        title: 'A signed lien waiver covering the net amount must be on file first.',
      }),
    );
  });

  it('marks a finance-approved pay application paid', async () => {
    paidMock.mockResolvedValue(payment('paid'));
    renderActions('finance_approved');
    fireEvent.click(screen.getByTestId('pay-app-mark-paid'));
    await waitFor(() => expect(paidMock).toHaveBeenCalledWith('pa-1'));
  });

  it('rejects only with a reason, and sends the one typed', async () => {
    rejectMock.mockResolvedValue(payment('rejected'));
    renderActions('submitted');
    fireEvent.click(screen.getByTestId('pay-app-reject'));
    const confirm = screen.getByTestId('pay-app-reject-confirm') as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByTestId('pay-app-reject-reason'), { target: { value: '  Work not done  ' } });
    fireEvent.click(confirm);
    await waitFor(() => expect(rejectMock).toHaveBeenCalledWith('pa-1', 'Work not done'));
  });

  it.each(['paid', 'rejected'] as const)('offers no step once the pay application is %s', (status) => {
    renderActions(status);
    expect(screen.queryByTestId('pay-app-reject')).toBeNull();
    expect(screen.queryByTestId('pay-app-mark-paid')).toBeNull();
    expect(screen.getByTestId('pay-app-lines-open')).toBeInTheDocument();
  });

  it('shows an approval below the claim on the lines of a paid pay application', async () => {
    linesMock.mockResolvedValue([
      {
        id: 'pal-1',
        payment_application_id: 'pa-1',
        work_package_id: 'wp-1',
        claimed_amount: '2000.00',
        certified_amount: '0.00',
        approved_amount: '1500.00',
      },
    ]);
    renderActions('paid');
    fireEvent.click(screen.getByTestId('pay-app-lines-open'));
    await screen.findByTestId('pay-app-lines');
    expect(screen.queryByTestId('pay-app-approved-input')).toBeNull();
    expect(screen.getByText('Footings')).toBeInTheDocument();
    expect(screen.getByTestId('pay-app-line-gap').textContent).toMatch(/500/);
  });

  it('shows what is payable as a line is lowered, at the agreement rate', async () => {
    renderActions('foreman_approved', false, { retentionPercent: '5' });
    const input = await openApproval();
    // 2000 claimed at 5%: 1900 payable as it stands.
    expect(screen.getByTestId('pay-app-payable').textContent).toMatch(/1,?900/);
    fireEvent.change(input, { target: { value: '1500' } });
    // 1500 approved less 75 retention.
    expect(screen.getByTestId('pay-app-payable').textContent).toMatch(/1,?425/);
  });

  it('works the payable out at the claim rate when the agreement rate is not given', async () => {
    renderActions('foreman_approved');
    const input = await openApproval();
    fireEvent.change(input, { target: { value: '1500' } });
    // The claim was 2000 with 200 retained, so 10%: 1500 less 150.
    expect(screen.getByTestId('pay-app-payable').textContent).toMatch(/1,?350/);
  });

  it('shows the stored payable of an approved pay application, not the claimed net', async () => {
    renderActions('paid', false, {
      payment: { approved_gross_amount: '1500.00', approved_retention_amount: '150.00', approved_net_amount: '1350.00' },
    });
    fireEvent.click(screen.getByTestId('pay-app-lines-open'));
    await screen.findByTestId('pay-app-lines');
    const payable = screen.getByTestId('pay-app-payable').textContent ?? '';
    expect(payable).toMatch(/1,?350/);
    expect(payable).not.toMatch(/1,?800/);
  });

  it('says a pay application without lines feeds no progress claim', async () => {
    linesMock.mockResolvedValue([]);
    renderActions('foreman_approved');
    fireEvent.click(screen.getByTestId('pay-app-approve-payment'));
    const note = await screen.findByTestId('pay-app-no-lines');
    expect(note.textContent).toContain('Approving it approves its gross amount.');
    expect(note.textContent).toContain('It will not feed a progress claim until it has lines.');
    // Approved at its gross, 2000 at the claim's 10%.
    expect(screen.getByTestId('pay-app-payable').textContent).toMatch(/1,?800/);
  });
});

describe('PayAppAmount', () => {
  it('shows the approved figure with the claim beneath it once they differ', () => {
    render(<PayAppAmount claimed="1800.00" approved="1350.00" currency="USD" />);
    expect(document.body.textContent).toMatch(/1,?350/);
    expect(screen.getByTestId('pay-app-claimed-figure').textContent).toMatch(/Claimed.*1,?800/);
  });

  it('shows the claim alone before approval and when approved as claimed', () => {
    const { unmount } = render(<PayAppAmount claimed="1800.00" approved={null} currency="USD" />);
    expect(screen.queryByTestId('pay-app-claimed-figure')).toBeNull();
    expect(document.body.textContent).toMatch(/1,?800/);
    unmount();
    render(<PayAppAmount claimed="1800.00" approved="1800" currency="USD" />);
    expect(screen.queryByTestId('pay-app-claimed-figure')).toBeNull();
  });
});
