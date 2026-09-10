// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the delete affordance in <ContractDetailDrawer>.
//
// The backend has always been able to do this: ``delete_contract`` removes a
// draft and refuses anything that has left draft. ``deleteContract`` has always
// been exported from the api module too. What was missing was the button, and
// nothing could see that, because every layer a test usually looks at was
// healthy. The endpoint had tests, the api client had an export, and the screen
// simply never called it. Only a component test asks the question that was
// actually failing: does the user have a way to reach the rule.
//
// So this file asserts the affordance, and the two states around it that are
// easy to get wrong and invisible on a healthy screen:
//
//   * a contract that has left draft must not offer the control. Rendering a
//     button whose only possible outcome is a refusal from the endpoint is the
//     same defect one step over.
//   * the first click must open the confirmation, not delete. A destructive
//     action wired straight to its mutation is the classic version of this
//     mistake, and it looks identical in the markup.
//
// The contracts api module is stubbed, so no network is hit. The panels the
// drawer stacks below the workflow buttons are stubbed too: they own their own
// queries, and the parties panel carries per-party delete controls of its own,
// which would put a second delete-shaped button in the DOM and let the negative
// case pass or fail for a reason that has nothing to do with this guard.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  listContracts: vi.fn(),
  listProgressClaims: vi.fn(),
  listContractLines: vi.fn(),
  createContract: vi.fn(),
  createProgressClaim: vi.fn(),
  suspendContract: vi.fn(),
  resumeContract: vi.fn(),
  terminateContract: vi.fn(),
  closeContract: vi.fn(),
  cloneContract: vi.fn(),
  deleteContract: vi.fn(),
  listClauseTemplates: vi.fn(),
  submitClaim: vi.fn(),
  approveClaim: vi.fn(),
  certifyClaim: vi.fn(),
  rejectClaim: vi.fn(),
  markClaimPaid: vi.fn(),
  getContractDashboard: vi.fn(),
}));

vi.mock('@/features/finance/api', () => ({
  getRetentionLedger: vi.fn(),
}));

vi.mock('./ContractPartiesPanel', () => ({
  ContractPartiesPanel: () => <div data-testid="parties-panel" />,
}));

vi.mock('./ContractAnalyticsPanels', () => ({
  ContractAnalyticsPanels: () => <div data-testid="analytics-panels" />,
}));

vi.mock('./ComplianceGate', () => ({
  ComplianceGate: () => <div data-testid="compliance-gate" />,
}));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) =>
    sel({ addToast: vi.fn() }),
}));

import { ContractDetailDrawer } from './ContractsPage';
import * as api from './api';
import * as financeApi from '@/features/finance/api';
import type { ContractItem, ContractStatus } from './api';

const deleteMock = vi.mocked(api.deleteContract);
const linesMock = vi.mocked(api.listContractLines);
const claimsMock = vi.mocked(api.listProgressClaims);
const dashMock = vi.mocked(api.getContractDashboard);
const retentionMock = vi.mocked(financeApi.getRetentionLedger);

const CONTRACT_ID = 'c-1';

/** A draft contract with nothing under it yet, unless overridden. */
function contract(over: Partial<ContractItem> = {}): ContractItem {
  return {
    id: CONTRACT_ID,
    code: 'SC-014',
    title: 'Groundworks and piling',
    contract_type: 'lump_sum',
    counterparty_type: 'subcontractor',
    counterparty_id: 'sub-1',
    project_id: 'proj-1',
    parent_contract_id: null,
    start_date: '2026-03-02',
    end_date: '2026-11-30',
    total_value: 486000,
    original_contract_value: null,
    currency: 'EUR',
    retention_percent: 5,
    retention_release_event: 'practical_completion',
    status: 'draft',
    signed_at: null,
    template_code: null,
    template_version: null,
    terms: {},
    created_by: null,
    metadata: {},
    created_at: '2026-03-01T09:00:00Z',
    updated_at: '2026-03-01T09:00:00Z',
    ...over,
  };
}

function renderDrawer(status: ContractStatus = 'draft') {
  const onClose = vi.fn();
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <ContractDetailDrawer
          contractId={CONTRACT_ID}
          contracts={[contract({ status })]}
          onClose={onClose}
        />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { onClose };
}

/**
 * The drawer's own control. Anchored, because the confirmation's confirm button
 * is drawn from the same i18n key and reads "Delete" too; an unanchored match
 * finds both the moment the dialog is open.
 */
function deleteButton(): HTMLElement {
  return screen.getByRole('button', { name: /^Delete$/ });
}

function queryDeleteButton(): HTMLElement | null {
  return screen.queryByRole('button', { name: /^Delete$/ });
}

/** The confirmation's confirm button, by the test id the dialog already owns. */
function confirmButton(): HTMLElement {
  return screen.getByTestId('confirm-dialog-confirm');
}

beforeEach(() => {
  vi.clearAllMocks();
  linesMock.mockResolvedValue([]);
  // An envelope, not an array: the claim history reads `.items` and asks the
  // page whether it is the whole set. A bare array here would type-check
  // against nothing and destructure to undefined at runtime.
  claimsMock.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  dashMock.mockResolvedValue({
    contract_id: CONTRACT_ID,
    total_value: 486000,
    original_contract_value: null,
    agreed_variations: 0,
    current_contract_value: 486000,
    pending_variations: 0,
    forecast_contract_value: 486000,
    paid_to_date: 0,
    retention_held: 0,
    outstanding: 486000,
    claims_count: 0,
    change_orders_count: 0,
    gainshare_estimate: null,
    status: 'draft',
  });
  retentionMock.mockResolvedValue({
    project_id: 'proj-1',
    as_of: null,
    groups: [],
    totals: [],
  });
});

describe('<ContractDetailDrawer> delete', () => {
  it('offers the control on a draft', async () => {
    renderDrawer('draft');

    // The whole bug in one assertion: the endpoint allows this, so the screen
    // has to have somewhere to say it from.
    await waitFor(() => expect(deleteButton()).toBeInTheDocument());
  });

  it('does not offer the control once the contract has left draft', async () => {
    renderDrawer('active');

    // An active contract is the commercial record of the job and leaves through
    // its status, not through deletion. The endpoint refuses it, so a button
    // here would exist only to earn that refusal.
    await waitFor(() => expect(screen.getByTestId('parties-panel')).toBeInTheDocument());
    expect(queryDeleteButton()).not.toBeInTheDocument();
    expect(deleteMock).not.toHaveBeenCalled();
  });

  it('asks before deleting instead of deleting on the first click', async () => {
    renderDrawer('draft');

    fireEvent.click(deleteButton());

    // Awaiting the dialog does two things: it proves the click opened the
    // confirmation, and it gives a stray mutation the microtask it would need
    // to land. Asserting not-called synchronously after the click would pass
    // even on a button wired straight to the mutation.
    await waitFor(() => expect(confirmButton()).toBeInTheDocument());
    expect(deleteMock).not.toHaveBeenCalled();
  });

  it('deletes the contract it was opened on once confirmed', async () => {
    deleteMock.mockResolvedValue(undefined);
    renderDrawer('draft');

    fireEvent.click(deleteButton());
    await waitFor(() => expect(confirmButton()).toBeInTheDocument());
    fireEvent.click(confirmButton());

    await waitFor(() => expect(deleteMock).toHaveBeenCalledTimes(1));
    // The id, not the row position: the drawer finds its subject by id, and a
    // delete addressed at the wrong contract is worse than no delete at all.
    expect(deleteMock).toHaveBeenCalledWith(CONTRACT_ID);
  });

  it('closes the drawer once the delete succeeds', async () => {
    deleteMock.mockResolvedValue(undefined);
    const { onClose } = renderDrawer('draft');

    fireEvent.click(deleteButton());
    await waitFor(() => expect(confirmButton()).toBeInTheDocument());
    fireEvent.click(confirmButton());

    // The drawer looks its subject up by id out of the list it was handed. Once
    // the row is gone it renders nothing while still counting as open, so the
    // user is left staring at a backdrop over the register.
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it('deletes nothing when the confirmation is dismissed', async () => {
    renderDrawer('draft');

    fireEvent.click(deleteButton());
    await waitFor(() => expect(confirmButton()).toBeInTheDocument());
    // The repo's own dialog test matches cancel this way: the visible label can
    // carry a trailing identity marker that defeats an exact-text match.
    fireEvent.click(screen.getByText(/^Cancel/));

    await waitFor(() =>
      expect(screen.queryByTestId('confirm-dialog-confirm')).not.toBeInTheDocument(),
    );
    expect(deleteMock).not.toHaveBeenCalled();
  });
});
