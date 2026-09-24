// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the Close button in <ContractDetailDrawer> posts.
//
// Close agrees the final account and completes the contract. It used to state
// the contract value as the final contract value, so a final account agreed at
// a negotiated figure was overwritten with the contract sum as soon as somebody
// pressed it. The server now refuses to restate an agreed final account, so a
// button that still stated the figure would earn a 409 on exactly the contracts
// that were closed out properly. It states a status and no figures: without a
// final account the server reads them from the contract and its claims, and
// with one the figures on it stand.

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
import type { ContractItem } from './api';

const closeMock = vi.mocked(api.closeContract);
const CONTRACT_ID = 'c-1';

function activeContract(): ContractItem {
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
    original_contract_value: 486000,
    currency: 'EUR',
    retention_percent: 5,
    retention_release_event: 'substantial_completion',
    status: 'active',
    signed_at: '2026-03-02T09:00:00Z',
    template_code: null,
    template_version: null,
    terms: {},
    created_by: null,
    metadata: {},
    created_at: '2026-03-01T09:00:00Z',
    updated_at: '2026-03-02T09:00:00Z',
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listContractLines).mockResolvedValue([]);
  vi.mocked(api.listProgressClaims).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  vi.mocked(api.getContractDashboard).mockResolvedValue({
    contract_id: CONTRACT_ID,
    total_value: 486000,
    original_contract_value: 486000,
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
    status: 'active',
  });
  vi.mocked(financeApi.getRetentionLedger).mockResolvedValue({
    project_id: 'proj-1',
    as_of: null,
    groups: [],
    totals: [],
  });
});

describe('<ContractDetailDrawer> Close', () => {
  it('asks for an agreed final account and states no figures', async () => {
    closeMock.mockResolvedValue({} as Awaited<ReturnType<typeof api.closeContract>>);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter>
        <QueryClientProvider client={qc}>
          <ContractDetailDrawer contractId={CONTRACT_ID} contracts={[activeContract()]} onClose={vi.fn()} />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByTestId('contract-close'));

    await waitFor(() => expect(closeMock).toHaveBeenCalledTimes(1));
    expect(closeMock).toHaveBeenCalledWith(CONTRACT_ID, { contract_id: CONTRACT_ID, status: 'agreed' });
  });
});
