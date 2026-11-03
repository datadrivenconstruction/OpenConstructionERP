// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    budgetLedgerApi: {
      get: vi.fn(),
      createTransfer: vi.fn(),
      createModification: vi.fn(),
      remove: vi.fn(),
      step: vi.fn(),
    },
  };
});

vi.mock('@/features/costmodel/CostLinePicker', () => ({
  CostLinePicker: ({
    value,
    onChange,
    'data-testid': testId,
  }: {
    value: string;
    onChange: (v: string) => void;
    'data-testid'?: string;
  }) => (
    <select data-testid={testId} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="" />
      <option value="l-1">331</option>
      <option value="l-2">360</option>
    </select>
  ),
}));

import { budgetLedgerApi, type BudgetLedger } from '../api';
import { BudgetLedgerPanel } from '../BudgetLedgerPanel';

const LEDGER: BudgetLedger = {
  project_id: 'p-1',
  currency: 'EUR',
  transfers: [
    {
      id: 't-1',
      code: 'BT-001',
      status: 'draft',
      reason: 'Walls over, roof under',
      legs: [
        { cost_line_id: 'l-1', code: '331', amount: '-500.00' },
        { cost_line_id: 'l-2', code: '360', amount: '500.00' },
      ],
      moved: '500.00',
      decision_note: '',
      created_at: null,
    },
    {
      id: 't-2',
      code: 'BT-002',
      status: 'submitted',
      reason: 'Slab',
      legs: [
        { cost_line_id: 'l-1', code: '331', amount: '-100.00' },
        { cost_line_id: 'l-2', code: '360', amount: '100.00' },
      ],
      moved: '100.00',
      decision_note: '',
      created_at: null,
    },
  ],
  modifications: [],
  lines: [],
  pending_transfers: 1,
  pending_modifications: 0,
  audit: [],
};

function renderPanel(canEdit: boolean, canManage: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BudgetLedgerPanel projectId="p-1" currency="EUR" canEdit={canEdit} canManage={canManage} />
    </QueryClientProvider>,
  );
}

describe('BudgetLedgerPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(budgetLedgerApi.get).mockResolvedValue(LEDGER);
    vi.mocked(budgetLedgerApi.step).mockResolvedValue(LEDGER.transfers[0]!);
  });

  it('lists transfers with their status and how many wait for a decision', async () => {
    renderPanel(true, true);
    expect(await screen.findByTestId('transfer-BT-001')).toBeTruthy();
    expect(screen.getByTestId('transfer-BT-002')).toBeTruthy();
    expect(screen.getByText(/1 waiting for a decision/)).toBeTruthy();
  });

  it('an editor can submit a draft but cannot approve', async () => {
    renderPanel(true, false);
    await screen.findByTestId('transfer-BT-001');
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(budgetLedgerApi.step).toHaveBeenCalledWith('p-1', 'transfer', 't-1', 'submit', ''));
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
  });

  it('a manager approves a submitted entry', async () => {
    renderPanel(false, true);
    await screen.findByTestId('transfer-BT-002');
    expect(screen.queryByRole('button', { name: 'Submit' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(budgetLedgerApi.step).toHaveBeenCalledWith('p-1', 'transfer', 't-2', 'approve', ''));
  });

  it('rejecting needs a reason', async () => {
    renderPanel(false, true);
    await screen.findByTestId('transfer-BT-002');
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    const confirm = screen.getAllByRole('button', { name: 'Reject' }).at(-1)!;
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Reason for rejecting'), { target: { value: 'No funds' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Reject' }).at(-1)!);
    await waitFor(() =>
      expect(budgetLedgerApi.step).toHaveBeenCalledWith('p-1', 'transfer', 't-2', 'reject', 'No funds'),
    );
  });

  it('a viewer sees the ledger but no buttons', async () => {
    renderPanel(false, false);
    await screen.findByTestId('transfer-BT-001');
    expect(screen.queryByRole('button', { name: 'Submit' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Move budget' })).toBeNull();
  });

  it('saves a transfer as two legs that add up to zero', async () => {
    vi.mocked(budgetLedgerApi.createTransfer).mockResolvedValue(LEDGER.transfers[0]!);
    renderPanel(true, false);
    await screen.findByTestId('transfer-BT-001');
    fireEvent.click(screen.getByRole('button', { name: 'Move budget' }));
    fireEvent.change(screen.getByTestId('ledger-from'), { target: { value: 'l-1' } });
    fireEvent.change(screen.getByTestId('ledger-to'), { target: { value: 'l-2' } });
    const inputs = screen.getAllByRole('textbox');
    fireEvent.change(inputs[0]!, { target: { value: '250' } });
    fireEvent.change(inputs[1]!, { target: { value: 'Walls over' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save as draft' }));
    await waitFor(() =>
      expect(budgetLedgerApi.createTransfer).toHaveBeenCalledWith('p-1', {
        reason: 'Walls over',
        legs: [
          { cost_line_id: 'l-1', amount: '-250.00' },
          { cost_line_id: 'l-2', amount: '250.00' },
        ],
      }),
    );
  });

  it('will not save a transfer from a line to itself', async () => {
    renderPanel(true, false);
    await screen.findByTestId('transfer-BT-001');
    fireEvent.click(screen.getByRole('button', { name: 'Move budget' }));
    fireEvent.change(screen.getByTestId('ledger-from'), { target: { value: 'l-1' } });
    fireEvent.change(screen.getByTestId('ledger-to'), { target: { value: 'l-1' } });
    const inputs = screen.getAllByRole('textbox');
    fireEvent.change(inputs[0]!, { target: { value: '250' } });
    fireEvent.change(inputs[1]!, { target: { value: 'x' } });
    expect((screen.getByRole('button', { name: 'Save as draft' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Choose two different cost lines.')).toBeTruthy();
  });
});
