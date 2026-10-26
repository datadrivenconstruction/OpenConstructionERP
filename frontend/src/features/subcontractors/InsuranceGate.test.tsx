// Subcontractor insurance tests​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pins the insurance gate on a pay application (banner, manager-only override
// dialog, held buttons), the status panel, the award banner badge and the
// project dashboard.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  getPaymentInsuranceCheck: vi.fn(),
  overridePaymentInsurance: vi.fn(),
  getSubcontractorInsuranceStatus: vi.fn(),
  getAwardEligibility: vi.fn(),
  getProjectInsurance: vi.fn(),
}));

vi.mock('./PaymentApprovalActions', () => ({
  PaymentApprovalActions: ({ insuranceBlocked }: { insuranceBlocked?: boolean }) => (
    <button type="button" data-testid="pay-app-approve-payment" disabled={insuranceBlocked}>
      approve
    </button>
  ),
}));

let role: string | null = 'manager';
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (sel: (s: { userRole: string | null }) => unknown) => sel({ userRole: role }),
}));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));
vi.mock('@/shared/hooks/useActiveProjectId', () => ({ useActiveProjectId: () => 'p1' }));

import * as api from './api';
import type { PaymentApplication, PaymentInsuranceStatus } from './api';
import { PaymentRowActions } from './PaymentInsuranceGate';
import { InsuranceStatusPanel } from './InsuranceStatusPanel';
import { AwardEligibilityBanner } from './AwardEligibilityBanner';
import { ProjectInsuranceDashboard } from './ProjectInsuranceDashboard';

const checkMock = vi.mocked(api.getPaymentInsuranceCheck);
const overrideMock = vi.mocked(api.overridePaymentInsurance);

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const payment = { id: 'pay1', status: 'foreman_approved', application_number: 'PA-1' } as PaymentApplication;
const blocked: PaymentInsuranceStatus = {
  payment_application_id: 'pay1',
  subcontractor_id: 's1',
  blocked: true,
  reasons: ['expired_mandatory_certificate:public_liability:2026-05-01'],
  overridden: false,
  certificates: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  role = 'manager';
});

describe('PaymentInsuranceGate', () => {
  it('holds the approve button and shows the reasons while insurance has lapsed', async () => {
    checkMock.mockResolvedValue(blocked);
    wrap(<PaymentRowActions payment={payment} requiresWaiver={false} />);
    const banner = await screen.findByTestId('insurance-gate-banner');
    expect(banner.textContent).toContain('Public liability');
    expect((screen.getByTestId('pay-app-approve-payment') as HTMLButtonElement).disabled).toBe(true);
  });

  it('lets a manager override with a reason of at least 10 characters', async () => {
    checkMock.mockResolvedValue(blocked);
    overrideMock.mockResolvedValue({
      id: 'o1', reason: 'Renewal in transit', covered_reasons: [], overridden_by: 'm', overridden_at: '2026-06-01T00:00:00Z',
    });
    wrap(<PaymentRowActions payment={payment} requiresWaiver={false} />);
    fireEvent.click(await screen.findByTestId('insurance-override-open'));
    const confirm = (await screen.findByTestId('insurance-override-confirm')) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByTestId('insurance-override-reason'), { target: { value: 'Renewal in transit' } });
    expect(confirm.disabled).toBe(false);
    fireEvent.click(confirm);
    await waitFor(() => expect(overrideMock).toHaveBeenCalledWith('pay1', 'Renewal in transit'));
  });

  it('offers no override to a role below manager', async () => {
    role = 'editor';
    checkMock.mockResolvedValue(blocked);
    wrap(<PaymentRowActions payment={payment} requiresWaiver={false} />);
    await screen.findByTestId('insurance-gate-banner');
    expect(screen.queryByTestId('insurance-override-open')).toBeNull();
  });

  it('releases the button and shows who overrode once an override is on file', async () => {
    checkMock.mockResolvedValue({
      ...blocked,
      overridden: true,
      override: { id: 'o1', reason: 'Renewal in transit', covered_reasons: [], overridden_by: 'm1', overridden_at: '2026-06-01T10:00:00Z' },
    });
    wrap(<PaymentRowActions payment={payment} requiresWaiver={false} />);
    expect((await screen.findByTestId('insurance-override-note')).textContent).toContain('Renewal in transit');
    expect((screen.getByTestId('pay-app-approve-payment') as HTMLButtonElement).disabled).toBe(false);
  });
});

describe('insurance status', () => {
  it('lists certificates with their alert bucket and the mandatory flag', async () => {
    vi.mocked(api.getSubcontractorInsuranceStatus).mockResolvedValue({
      subcontractor_id: 's1', as_of: '2026-06-01', status: 'expiring', payment_blocked: false, reasons: [], findings: [],
      certificates: [
        {
          id: 'c1', subcontractor_id: 's1', cert_type: 'public_liability', is_mandatory: true, revoked: false,
          bucket: 'due_14', valid_until: '2026-06-10', policy_number: 'PL-1', coverage_amount: '5000000', coverage_currency: 'EUR',
        },
      ],
    });
    wrap(<InsuranceStatusPanel subcontractorId="s1" />);
    const row = await screen.findByTestId('insurance-cert-row');
    expect(row.getAttribute('data-bucket')).toBe('due_14');
    expect(row.textContent).toContain('Mandatory');
    expect(row.textContent).toContain('PL-1');
    expect(screen.getByTestId('insurance-status-badge').getAttribute('data-status')).toBe('expiring');
  });

  it('shows the insurance verdict as a badge in the award banner', async () => {
    vi.mocked(api.getAwardEligibility).mockResolvedValue({
      subcontractor_id: 's1', awardable: true, reasons: [], insurance_status: 'non_compliant',
    });
    wrap(<AwardEligibilityBanner subcontractorId="s1" prequalStatus="approved" isBlocked={false} />);
    const badge = await screen.findByTestId('insurance-status-badge');
    expect(badge.getAttribute('data-status')).toBe('non_compliant');
  });

  it('shows no insurance badge when the register has nothing on file', async () => {
    vi.mocked(api.getAwardEligibility).mockResolvedValue({
      subcontractor_id: 's1', awardable: true, reasons: [], insurance_status: null,
    });
    wrap(<AwardEligibilityBanner subcontractorId="s1" prequalStatus="approved" isBlocked={false} />);
    await waitFor(() => expect(api.getAwardEligibility).toHaveBeenCalled());
    expect(screen.queryByTestId('insurance-status-badge')).toBeNull();
  });
});

describe('ProjectInsuranceDashboard', () => {
  it('shows counts, buckets and the held pay applications', async () => {
    vi.mocked(api.getProjectInsurance).mockResolvedValue({
      project_id: 'p1', as_of: '2026-06-01',
      counts: { compliant: 3, expiring: 1, non_compliant: 2 },
      certificate_buckets: { valid: 8, due_30: 1, expired: 2 },
      subcontractors: [],
      gated_payments: [
        {
          payment_application_id: 'pay1', application_number: 'PA-7', subcontractor_id: 's1', status: 'foreman_approved',
          net_amount: '1000.00', currency: 'EUR', blocked: true, overridden: false, reasons: [],
        },
      ],
    });
    wrap(<ProjectInsuranceDashboard />);
    expect((await screen.findByTestId('insurance-count-non_compliant')).textContent).toContain('2');
    expect(screen.getByTestId('insurance-bucket-expired').textContent).toContain('2');
    expect(screen.getByTestId('insurance-gated-payment').textContent).toContain('PA-7');
  });
});
