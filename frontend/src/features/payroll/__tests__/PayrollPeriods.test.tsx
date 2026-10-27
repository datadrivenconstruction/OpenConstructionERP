// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// <PayrollPeriodsSection />​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: lock, reopen asks for a reason, a blocked export
// shows the findings the server sent.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const toastMocks = vi.hoisted(() => ({ addToast: vi.fn() }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: { addToast: typeof toastMocks.addToast }) => unknown) =>
      selector({ addToast: toastMocks.addToast }),
    { getState: () => ({ addToast: toastMocks.addToast }) },
  ),
}));

vi.mock('../api', async () => {
  class PeriodExportError extends Error {
    constructor(
      public readonly status: number,
      public readonly messages: string[],
    ) {
      super(messages.join('; '));
    }
  }
  return {
    PeriodExportError,
    PAY_TYPES: ['regular', 'overtime', 'overtime_weekly', 'night_premium', 'saturday', 'sunday', 'holiday', 'per_diem'],
    EXPORT_COLUMNS: ['employee_number', 'employee', 'project', 'cost_code', 'work_date', 'pay_type', 'hours', 'rate', 'multiplier', 'amount', 'currency', 'employee_id', 'project_id', 'overtime_approved', 'period_start', 'period_end'],
    fetchRuleProfiles: vi.fn(),
    fetchPeriods: vi.fn(),
    fetchPeriod: vi.fn(),
    createPeriod: vi.fn(),
    rebuildPeriod: vi.fn(),
    lockPeriod: vi.fn(),
    reopenPeriod: vi.fn(),
    postPeriodCosts: vi.fn(),
    downloadPeriodExport: vi.fn(),
  };
});

import {
  PeriodExportError,
  fetchRuleProfiles,
  fetchPeriods,
  fetchPeriod,
  lockPeriod,
  reopenPeriod,
  downloadPeriodExport,
} from '../api';
import type { PeriodDetail, PeriodHeader, RuleProfile } from '../api';
import { PayrollPeriodsSection } from '../PayrollPeriodsSection';

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const PROFILE: RuleProfile = {
  profile: 'de_default',
  country: 'DE',
  label: 'Germany default',
  source: 'test',
  confidence: 'medium',
  needs_expert_review: false,
  burden_pct: null,
  flags: [],
  has_lodas: true,
};

const HEADER: PeriodHeader = {
  id: 'per-1',
  project_id: 'proj-1',
  label: 'June 2026',
  period_start: '2026-06-01',
  period_end: '2026-06-30',
  country: 'DE',
  rule_profile: 'de_default',
  status: 'open',
  currency: 'EUR',
  total_hours: '170.00',
  total_gross: '5100.00',
  total_burden: '0',
  flags: [],
};

const DETAIL: PeriodDetail = {
  ...HEADER,
  locked_at: null,
  exported_at: null,
  posted_ref: null,
  certified_payroll_weeks: [],
  totals_by_type: { regular: { hours: '160.00', amount: '4800.00' }, overtime: { hours: '10.00', amount: '300.00' } },
  lines: [
    {
      id: 'l1',
      employee_id: 'emp-1',
      employee_number: '17',
      employee_name: 'Anna Beispiel',
      work_date: '2026-06-02',
      cost_code: '300',
      pay_type: 'regular',
      hours: '8.00',
      rate: '30.00',
      multiplier: '1.00',
      amount: '240.00',
      overtime_approved: false,
    },
  ],
  events: [],
  findings: [],
};

const LOCKED: PeriodDetail = {
  ...DETAIL,
  status: 'locked',
  locked_at: '2026-07-01T08:00:00Z',
  events: [{ action: 'reopened', reason: 'Missed hours', actor_id: null, created_at: '2026-07-02T09:00:00Z', details: null }],
};

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <PayrollPeriodsSection projectId="proj-1" />
    </QueryClientProvider>,
  );
}

async function openPeriod() {
  renderSection();
  fireEvent.click(await screen.findByText('June 2026'));
  await waitFor(() => expect(fetchPeriod).toHaveBeenCalledWith('per-1'));
  await screen.findByTestId('period-detail');
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  asMock(fetchRuleProfiles).mockResolvedValue([PROFILE]);
  asMock(fetchPeriods).mockResolvedValue([HEADER]);
  asMock(fetchPeriod).mockResolvedValue(DETAIL);
});

afterEach(() => cleanup());

describe('<PayrollPeriodsSection />', () => {
  it('locks an open period', async () => {
    asMock(lockPeriod).mockResolvedValue(LOCKED);
    await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: /Lock period/i }));
    await waitFor(() => expect(lockPeriod).toHaveBeenCalledWith('per-1'));
    await waitFor(() =>
      expect(toastMocks.addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' })),
    );
  });

  it('reopen asks for a reason of at least 3 characters before calling the API', async () => {
    asMock(fetchPeriod).mockResolvedValue(LOCKED);
    asMock(reopenPeriod).mockResolvedValue(DETAIL);
    await openPeriod();
    expect(screen.getByTestId('locked-note')).toBeTruthy();
    expect(screen.getByTestId('audit-trail').textContent).toContain('Missed hours');

    fireEvent.click(screen.getByRole('button', { name: /^Reopen period$/i }));
    const dialog = await screen.findByRole('dialog');
    const confirm = Array.from(dialog.querySelectorAll('button')).find((b) =>
      /Reopen period/i.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    expect(reopenPeriod).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Reason/i), { target: { value: 'ab' } });
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Reason/i), { target: { value: 'Missed hours' } });
    expect(confirm.disabled).toBe(false);
    fireEvent.click(confirm);
    await waitFor(() => expect(reopenPeriod).toHaveBeenCalledWith('per-1', 'Missed hours'));
  });

  it('a blocked export shows the findings from the server', async () => {
    asMock(downloadPeriodExport).mockRejectedValue(
      new PeriodExportError(409, ['Employee 17 has no pay rate', 'Overtime is not approved on 2026-06-05']),
    );
    await openPeriod();
    fireEvent.click(screen.getByRole('button', { name: /Export period/i }));
    const box = await screen.findByTestId('export-errors');
    expect(box.textContent).toContain('Employee 17 has no pay rate');
    expect(box.textContent).toContain('Overtime is not approved on 2026-06-05');
    expect(downloadPeriodExport).toHaveBeenCalledWith(
      'per-1',
      expect.objectContaining({ format: 'csv' }),
    );
  });
});
