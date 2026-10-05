// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for <PaymentPlanPanel>, the payment plan in the contract
// drawer.
//
// What these pin, each a way the panel could look right and be wrong:
//
//   * A reached instalment raises its claim once. A double click that raised
//     two drafts would bill the client twice for one stage, and the claim
//     history, the claims register and the dashboard all have to hear about
//     the one that was raised.
//   * A viewer reads the plan and is offered nothing that answers 403.
//   * The schedule picker offers milestones, not every task in the
//     programme, and a link goes through its own route, whose warnings are
//     shown in words.
//   * An edit sends only what changed. A switch from a fixed amount to a
//     percentage clears the amount, which would otherwise keep winning, and
//     an emptied box goes as an explicit null so the server clears it.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const toast = vi.hoisted(() => vi.fn());
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof toast }) => unknown) => sel({ addToast: toast }),
}));

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  getPaymentPlan: vi.fn(),
  raiseMilestoneClaim: vi.fn(),
  updateContractMilestone: vi.fn(),
  createContractMilestone: vi.fn(),
  deleteContractMilestone: vi.fn(),
  linkMilestoneActivity: vi.fn(),
  listScheduleMilestoneCandidates: vi.fn(),
}));

import { PaymentPlanPanel } from './PaymentPlanPanel';
import * as api from './api';
import type { PaymentPlan, PaymentPlanLine, ProgressClaimItem } from './api';
import { ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

const CONTRACT_ID = 'ct-1';
const PROJECT_ID = 'pr-1';

function line(id: string, extra: Partial<PaymentPlanLine> = {}): PaymentPlanLine {
  return {
    id,
    contract_id: CONTRACT_ID,
    code: '',
    name: `Stage ${id}`,
    planned_date: '2026-11-02',
    value: '10000',
    percent_of_contract: null,
    trigger: 'completion',
    status: 'pending',
    kind: 'progress',
    activity_id: null,
    schedule_id: null,
    lag_days: 0,
    payment_terms_days: null,
    forecast_reached_date: '2026-11-02',
    forecast_due_date: '2026-11-16',
    reached_at: null,
    client_visible: false,
    metadata: {},
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    forecast_at: null,
    amount: '10000',
    activity_name: null,
    activity_missing: false,
    client_status: 'upcoming',
    days_moved: null,
    claim_id: null,
    claim_status: null,
    ...extra,
  };
}

function plan(lines: PaymentPlanLine[], extra: Partial<PaymentPlan> = {}): PaymentPlan {
  return {
    contract_id: CONTRACT_ID,
    currency: 'EUR',
    contract_total: '100000',
    scheduled_total: '30000',
    percent_scheduled: '30.00',
    default_payment_terms_days: 14,
    lines,
    findings: [],
    ...extra,
  };
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(qc, 'invalidateQueries');
  render(
    <QueryClientProvider client={qc}>
      <PaymentPlanPanel contractId={CONTRACT_ID} projectId={PROJECT_ID} currency="EUR" />
    </QueryClientProvider>,
  );
  return { invalidate };
}

// Typed by shape: `ReturnType<typeof vi.spyOn>` resolves through an overloaded
// generic signature, and this file is compiled by `tsc -b` with the rest of src.
function invalidatedKeys(spy: { mock: { calls: unknown[][] } }): string[] {
  return spy.mock.calls.map((c) => JSON.stringify((c[0] as { queryKey: unknown }).queryKey));
}

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom has no layout; the picker scrolls its highlighted row into view.
  Element.prototype.scrollIntoView = vi.fn();
  useAuthStore.setState({ userRole: 'editor' });
});

describe('raising the claim for a reached instalment', () => {
  it('raises it once, however often it is clicked, and refreshes everything that counts claims', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(
      plan([line('a', { status: 'reached', client_status: 'due' }), line('b')]),
    );
    let finish: (v: ProgressClaimItem) => void = () => {};
    vi.mocked(api.raiseMilestoneClaim).mockReturnValue(
      new Promise<ProgressClaimItem>((resolve) => {
        finish = resolve;
      }),
    );
    const { invalidate } = renderPanel();

    // Only the reached line offers a claim.
    const buttons = await screen.findAllByRole('button', { name: 'Create claim' });
    expect(buttons).toHaveLength(1);
    const reachedRow = screen.getByTestId('plan-line-a');
    expect(within(reachedRow).getByRole('button', { name: 'Create claim' })).toBe(buttons[0]);

    fireEvent.click(buttons[0]!);
    fireEvent.click(buttons[0]!);
    await waitFor(() => expect(api.raiseMilestoneClaim).toHaveBeenCalledWith('a'));
    fireEvent.click(buttons[0]!);
    expect(api.raiseMilestoneClaim).toHaveBeenCalledTimes(1);

    finish({ id: 'cl-1', claim_number: 'PC-007' } as ProgressClaimItem);
    await waitFor(() => {
      const keys = invalidatedKeys(invalidate);
      expect(keys).toContain(JSON.stringify(['contracts', 'payment-plan', CONTRACT_ID]));
      expect(keys).toContain(JSON.stringify(['contracts', 'claims']));
      expect(keys).toContain(JSON.stringify(['contracts', 'claim-history', CONTRACT_ID]));
      expect(keys).toContain(JSON.stringify(['contracts', 'dashboard', CONTRACT_ID]));
    });
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success', title: expect.stringContaining('PC-007') }),
    );
  });

  it('offers no claim for a line a claim already bills, and shows that claim', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(
      plan([line('a', { status: 'reached', claim_id: 'cl-1', claim_status: 'draft' })]),
    );
    renderPanel();
    expect(await screen.findByText('Draft')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create claim' })).toBeNull();
  });

  it('says in words that someone else claimed it first, and reloads the plan', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([line('a', { status: 'reached' })]));
    vi.mocked(api.raiseMilestoneClaim).mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: { error: 'milestone_already_claimed', message: 'Claim PC-001 already bills this instalment.' },
      }),
    );
    const { invalidate } = renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Create claim' }));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith({
        type: 'error',
        title: 'A claim already bills this instalment.',
      }),
    );
    expect(invalidatedKeys(invalidate)).toContain(JSON.stringify(['contracts', 'payment-plan', CONTRACT_ID]));
  });

  it('says in words that the contract is already billed by measured progress', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([line('a', { status: 'reached' })]));
    vi.mocked(api.raiseMilestoneClaim).mockRejectedValue(
      new ApiError(409, 'Conflict', {
        detail: { error: 'contract_billed_by_progress', message: 'This contract is billed by measured progress.' },
      }),
    );
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Create claim' }));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith({
        type: 'error',
        title: expect.stringContaining('would bill the same work twice'),
      }),
    );
  });
});

describe('what a viewer is offered', () => {
  it('reads the plan and gets no button that would answer 403', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    vi.mocked(api.getPaymentPlan).mockResolvedValue(
      plan([line('a', { status: 'reached' }), line('b')]),
    );
    renderPanel();
    expect(await screen.findByText('Stage a')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Create claim' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mark as reached' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Add instalment' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete instalment' })).toBeNull();
    expect(screen.getByText('You can read this plan. Changing it needs editor rights.')).toBeTruthy();
  });

  it('keeps deleting for a manager, as the backend does', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([line('a')]));
    renderPanel();
    expect(await screen.findByRole('button', { name: 'Edit' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Delete instalment' })).toBeNull();
  });
});

describe('the schedule milestone picker', () => {
  it('offers milestones only, links through the link route and says what its warnings mean', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([line('a', { trigger: 'date' })]));
    vi.mocked(api.listScheduleMilestoneCandidates).mockResolvedValue([
      { id: 'act-roof', name: 'Roof finished', wbs_code: '1.4', end_date: '2026-11-20', schedule_id: 's-1', schedule_name: 'Main programme', is_milestone: true },
      { id: 'act-brick', name: 'Brickwork', wbs_code: '1.2', end_date: '2026-10-30', schedule_id: 's-1', schedule_name: 'Main programme', is_milestone: false },
    ]);
    vi.mocked(api.updateContractMilestone).mockResolvedValue(line('a') as never);
    vi.mocked(api.linkMilestoneActivity).mockResolvedValue({
      ...line('a', { activity_id: 'act-roof' }),
      warnings: ['date_trigger_ignores_schedule'],
    });
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const picker = await screen.findByTestId('schedule-milestone-picker');
    await waitFor(() => expect(api.listScheduleMilestoneCandidates).toHaveBeenCalledWith(PROJECT_ID));
    fireEvent.click(picker);
    expect(await screen.findByRole('option', { name: /Roof finished/ })).toBeTruthy();
    expect(screen.queryByRole('option', { name: /Brickwork/ })).toBeNull();
    fireEvent.click(screen.getByRole('option', { name: /Roof finished/ }));

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.linkMilestoneActivity).toHaveBeenCalledWith('a', 'act-roof'));
    // Only the link changed, so nothing else is written: the link has its own route.
    expect(api.updateContractMilestone).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'warning', title: expect.stringContaining('fixed date') }),
      ),
    );
  });

  it('keeps showing an activity the line is linked to even when it is a task', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(
      plan([line('a', { activity_id: 'act-brick', activity_name: 'Brickwork' })]),
    );
    vi.mocked(api.listScheduleMilestoneCandidates).mockResolvedValue([
      { id: 'act-brick', name: 'Brickwork', wbs_code: '1.2', end_date: null, schedule_id: 's-1', schedule_name: 'Main programme', is_milestone: false },
    ]);
    renderPanel();
    expect(await screen.findByText('Waits for: Brickwork')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    const picker = await screen.findByTestId('schedule-milestone-picker');
    await waitFor(() => expect(picker.textContent).toContain('Brickwork'));
  });

  it('unlinks with null through the link route', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(
      plan([line('a', { activity_id: 'act-roof', activity_name: 'Roof finished' })]),
    );
    vi.mocked(api.listScheduleMilestoneCandidates).mockResolvedValue([
      { id: 'act-roof', name: 'Roof finished', wbs_code: '1.4', end_date: null, schedule_id: 's-1', schedule_name: 'Main programme', is_milestone: true },
    ]);
    vi.mocked(api.updateContractMilestone).mockResolvedValue(line('a') as never);
    vi.mocked(api.linkMilestoneActivity).mockResolvedValue({ ...line('a'), warnings: [] });
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const picker = await screen.findByTestId('schedule-milestone-picker');
    await waitFor(() => expect(picker.textContent).toContain('Roof finished'));
    fireEvent.click(picker);
    fireEvent.click(await screen.findByRole('option', { name: 'Not linked to the schedule' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.linkMilestoneActivity).toHaveBeenCalledWith('a', null));
  });

  it('says to mark the activity as a milestone when the link route refuses a task', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([line('a')]));
    vi.mocked(api.listScheduleMilestoneCandidates).mockResolvedValue([
      { id: 'act-roof', name: 'Roof finished', wbs_code: '1.4', end_date: null, schedule_id: 's-1', schedule_name: 'Main programme', is_milestone: true },
    ]);
    vi.mocked(api.linkMilestoneActivity).mockRejectedValue(
      new ApiError(422, 'Unprocessable Content', {
        detail: { error: 'activity_not_milestone', message: 'This activity is not a milestone.' },
      }),
    );
    const { invalidate } = renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const picker = await screen.findByTestId('schedule-milestone-picker');
    await waitFor(() => expect(api.listScheduleMilestoneCandidates).toHaveBeenCalled());
    fireEvent.click(picker);
    fireEvent.click(await screen.findByRole('option', { name: /Roof finished/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith({
        type: 'error',
        title: expect.stringContaining('Mark it as a milestone in the schedule first.'),
      }),
    );
    expect(invalidatedKeys(invalidate)).toContain(JSON.stringify(['contracts', 'payment-plan', CONTRACT_ID]));
  });
});

describe('the line form', () => {
  it('links only on a second Save after a new line was written but its link failed', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([]));
    vi.mocked(api.listScheduleMilestoneCandidates).mockResolvedValue([
      { id: 'act-roof', name: 'Roof finished', wbs_code: '1.4', end_date: null, schedule_id: 's-1', schedule_name: 'Main programme', is_milestone: true },
    ]);
    vi.mocked(api.createContractMilestone).mockResolvedValue(line('n') as never);
    vi.mocked(api.linkMilestoneActivity).mockRejectedValue(
      new ApiError(422, 'Unprocessable Content', {
        detail: { error: 'activity_not_milestone', message: 'This activity is not a milestone.' },
      }),
    );
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Add instalment' }));
    fireEvent.change(screen.getByPlaceholderText('e.g. Roof finished'), { target: { value: 'Roof' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Amount (EUR)' }), { target: { value: '5000' } });
    await waitFor(() => expect(api.listScheduleMilestoneCandidates).toHaveBeenCalled());
    fireEvent.click(await screen.findByTestId('schedule-milestone-picker'));
    fireEvent.click(await screen.findByRole('option', { name: /Roof finished/ }));

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.linkMilestoneActivity).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' })),
    );
    await waitFor(() =>
      expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.linkMilestoneActivity).toHaveBeenCalledTimes(2));
    expect(api.createContractMilestone).toHaveBeenCalledTimes(1);
    expect(api.linkMilestoneActivity).toHaveBeenLastCalledWith('n', 'act-roof');
  });

  it('turns a saved fixed amount into a percentage by clearing the amount, and sends nothing else', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([line('a', { value: '10000', payment_terms_days: 30 })]));
    vi.mocked(api.updateContractMilestone).mockResolvedValue(line('a') as never);
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.click(await screen.findByRole('radio', { name: 'Percent of the contract' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Percent of the contract' }), {
      target: { value: '12,5' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.updateContractMilestone).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.updateContractMilestone).mock.calls[0]).toEqual([
      'a',
      { value: null, percent_of_contract: '12.5' },
    ]);
  });

  it('clears the payment terms when the box is emptied', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([line('a', { payment_terms_days: 30 })]));
    vi.mocked(api.updateContractMilestone).mockResolvedValue(line('a') as never);
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const terms = await screen.findByDisplayValue('30');
    fireEvent.change(terms, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.updateContractMilestone).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.updateContractMilestone).mock.calls[0]).toEqual(['a', { payment_terms_days: null }]);
  });

  it('says that an approval waits for a person, not for the schedule', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([line('a')]));
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(await screen.findByText(/as soon as the schedule marks the milestone done/)).toBeTruthy();
    fireEvent.change(screen.getByDisplayValue('When the work is finished'), { target: { value: 'approval' } });
    expect(screen.getByText(/never approves the work/)).toBeTruthy();
    expect(screen.queryByText(/as soon as the schedule marks the milestone done/)).toBeNull();
  });

  it('creates a percentage line with the percentage, not an amount', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(plan([]));
    vi.mocked(api.createContractMilestone).mockResolvedValue(line('n') as never);
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Add instalment' }));
    fireEvent.change(screen.getByPlaceholderText('e.g. Roof finished'), { target: { value: 'Deposit' } });
    fireEvent.click(screen.getByRole('radio', { name: 'Percent of the contract' }));
    const percentBox = screen.getByRole('textbox', { name: 'Percent of the contract' });
    fireEvent.change(percentBox, { target: { value: '12,5' } });
    expect(screen.getByText(/That is .*12,500\.00.* of .*100,000\.00/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.createContractMilestone).toHaveBeenCalledTimes(1));
    const body = vi.mocked(api.createContractMilestone).mock.calls[0]![1];
    expect(body).toMatchObject({ contract_id: CONTRACT_ID, name: 'Deposit', percent_of_contract: '12.5' });
    expect(body).not.toHaveProperty('value');
    // Nothing picked in the schedule, so no link call.
    expect(api.linkMilestoneActivity).not.toHaveBeenCalled();
  });
});

describe('findings', () => {
  it('heads each finding in the reader language and keeps the server message under it', async () => {
    vi.mocked(api.getPaymentPlan).mockResolvedValue(
      plan([line('a')], {
        findings: [
          {
            rule_id: 'payment_plan.percent_sum',
            severity: 'warning',
            message: 'The instalments add up to 30,000.00 of the contract sum of 100,000.00 (30.00%)',
            element_ref: CONTRACT_ID,
            suggestion: 'Add an instalment for the rest of the contract sum, or adjust the amounts',
            details: {},
          },
        ],
      }),
    );
    renderPanel();
    expect(await screen.findByText('Part of the contract has no instalment')).toBeTruthy();
    expect(screen.getByText(/add up to 30,000\.00 of the contract sum/)).toBeTruthy();
  });
});
