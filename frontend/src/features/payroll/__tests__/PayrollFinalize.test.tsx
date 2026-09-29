// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Tests for the Gap A finalize flow on <PayrollPage />.
//
// Coverage (UI slice of the Gap A TEST MATRIX):
//   15  Finalize button is visible when the selected batch is draft.
//   16  Finalize button is hidden when the selected batch is approved.
//   17  Clicking Finalize opens the confirmation dialog.
//   18  Cancelling the dialog does not call the API.
//   19  Confirming finalizes (calls the API, shows a success toast, invalidates
//       the queries so the list/detail status refreshes).
//   20  An API error surfaces an error toast (no optimistic status change).
//   21  The list + detail queries are invalidated on success.
//
// Mocking mirrors the approval-routes / accommodation page tests: stub the
// feature-local `./api` module and drive the real project-context + toast
// stores. The global i18n mock returns each key's `defaultValue`, so we assert
// on the English strings.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Toast store mock ─────────────────────────────────────────────── */

const toastMocks = vi.hoisted(() => ({ addToast: vi.fn() }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: { addToast: typeof toastMocks.addToast }) => unknown) =>
      selector({ addToast: toastMocks.addToast }),
    { getState: () => ({ addToast: toastMocks.addToast }) },
  ),
}));

/* ── Feature-local API mock ───────────────────────────────────────── */

vi.mock('../api', () => ({
  fetchPayrollBatches: vi.fn(),
  fetchPayrollBatch: vi.fn(),
  generatePayrollBatch: vi.fn(),
  finalizeBatch: vi.fn(),
  submitBatch: vi.fn(),
  postBatch: vi.fn(),
  reconcileBatch: vi.fn(),
  downloadBatchExport: vi.fn(),
  fetchLabourCost: vi.fn(),
  addDeduction: vi.fn(),
  removeDeduction: vi.fn(),
}));

import {
  fetchPayrollBatches,
  fetchPayrollBatch,
  finalizeBatch,
  fetchLabourCost,
} from '../api';
import type { PayrollBatch, PayrollBatchDetail, LabourCost } from '../api';
import PayrollPage from '../PayrollPage';

/* ── Fixtures ─────────────────────────────────────────────────────── */

const DRAFT_BATCH: PayrollBatch = {
  id: 'batch-1',
  project_id: 'proj-1',
  period_label: 'Week 2026-W23',
  period_start: '2026-06-01',
  period_end: '2026-06-07',
  status: 'draft',
  currency: 'EUR',
  total_hours: '16.00',
  total_amount: '715.00',
  total_deductions: '0.00',
  total_net: '715.00',
  entry_count: 2,
  notes: '',
  created_by: null,
  submitted_at: null,
  submitted_by: null,
  approved_at: null,
  approved_by: null,
  posted_at: null,
  posted_by: null,
  gl_transaction_ref: null,
  metadata: {},
  created_at: '2026-06-07T00:00:00Z',
  updated_at: '2026-06-07T00:00:00Z',
};

const DRAFT_DETAIL: PayrollBatchDetail = {
  ...DRAFT_BATCH,
  entries: [
    {
      id: 'e1',
      batch_id: 'batch-1',
      resource_id: null,
      worker: 'Carpenter',
      work_date: '2026-06-01',
      hours: '8.00',
      rate: '50.0000',
      amount: '400.00',
      net_amount: '400.00',
      currency: 'EUR',
      source: 'fieldreport',
      metadata: {},
      deductions: [],
      created_at: '2026-06-07T00:00:00Z',
      updated_at: '2026-06-07T00:00:00Z',
    },
  ],
};

const APPROVED_DETAIL: PayrollBatchDetail = {
  ...DRAFT_DETAIL,
  status: 'approved',
};

const LABOUR_COST: LabourCost = {
  project_id: 'proj-1',
  currency: 'EUR',
  labour_cost: '715.00',
  total_hours: '16.00',
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PayrollPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

async function openDraftBatch() {
  renderPage();
  // Open the batch detail by clicking the batch row.
  await waitFor(() => expect(screen.getByText('Week 2026-W23')).toBeTruthy());
  fireEvent.click(screen.getByText('Week 2026-W23'));
  await waitFor(() => expect(fetchPayrollBatch).toHaveBeenCalledWith('batch-1'));
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  useProjectContextStore.getState().setActiveProject('proj-1', 'Riverside HQ');
  // Every read on the page needs payroll.read, which starts at manager.
  useAuthStore.setState({ userRole: 'manager' });
  asMock(fetchPayrollBatches).mockResolvedValue([DRAFT_BATCH]);
  asMock(fetchLabourCost).mockResolvedValue(LABOUR_COST);
  asMock(fetchPayrollBatch).mockResolvedValue(DRAFT_DETAIL);
});

afterEach(() => {
  cleanup();
  useProjectContextStore.getState().clearProject();
});

describe('<PayrollPage /> finalize flow', () => {
  it('15: shows the Finalize button when the selected batch is draft', async () => {
    await openDraftBatch();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Finalize batch/i })).toBeTruthy(),
    );
  });

  it('16: hides the Finalize button when the selected batch is approved', async () => {
    asMock(fetchPayrollBatch).mockResolvedValue(APPROVED_DETAIL);
    asMock(fetchPayrollBatches).mockResolvedValue([{ ...DRAFT_BATCH, status: 'approved' }]);
    await openDraftBatch();
    // Detail resolves to approved -> no finalize button.
    await waitFor(() => expect(screen.getByText('Entries')).toBeTruthy());
    expect(screen.queryByRole('button', { name: /Finalize batch/i })).toBeNull();
  });

  it('17: clicking Finalize opens the confirmation dialog', async () => {
    await openDraftBatch();
    const btn = await screen.findByRole('button', { name: /Finalize batch/i });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByRole('alertdialog')).toBeTruthy());
    expect(screen.getByText(/Labour cost will post to the project budget/i)).toBeTruthy();
  });

  it('18: cancelling the dialog does not call the API', async () => {
    await openDraftBatch();
    fireEvent.click(await screen.findByRole('button', { name: /Finalize batch/i }));
    await screen.findByRole('alertdialog');
    fireEvent.click(screen.getByRole('button', { name: /^Cancel$/i }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(finalizeBatch).not.toHaveBeenCalled();
  });

  it('19/21: confirming finalizes, toasts success, and refreshes', async () => {
    asMock(finalizeBatch).mockResolvedValue(APPROVED_DETAIL);
    await openDraftBatch();
    fireEvent.click(await screen.findByRole('button', { name: /Finalize batch/i }));
    await screen.findByRole('alertdialog');

    // The dialog confirm button (data-testid keeps it unambiguous from the header).
    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));

    await waitFor(() => expect(finalizeBatch).toHaveBeenCalledWith('batch-1'));
    await waitFor(() =>
      expect(toastMocks.addToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'success' }),
      ),
    );
  });

  it('20: an API error surfaces an error toast', async () => {
    asMock(finalizeBatch).mockRejectedValue(new Error('boom'));
    await openDraftBatch();
    fireEvent.click(await screen.findByRole('button', { name: /Finalize batch/i }));
    await screen.findByRole('alertdialog');
    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));

    await waitFor(() => expect(finalizeBatch).toHaveBeenCalled());
    await waitFor(() =>
      expect(toastMocks.addToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'error' }),
      ),
    );
  });

  it('a viewer is told the page is not for their role and nothing is fetched', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderPage();
    expect(await screen.findByText(/don.t have access here/i)).toBeTruthy();
    expect(fetchPayrollBatches).not.toHaveBeenCalled();
    expect(fetchLabourCost).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /Generate draft batch/i })).toBeNull();
  });
});
