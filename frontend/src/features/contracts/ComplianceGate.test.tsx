// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The signature gate names the schedule line a finding is about. It used to
// print the line's id, which nobody on site can map back to a line.

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const LINE_ID = '7f1c2a9e-5b1d-4e8a-9c3f-2d6b8a0e4f11';
const OTHER_ID = '0b9d4e2a-1c3f-4a5b-8d7e-6f5a4b3c2d1e';

vi.mock('./api', () => ({
  signContract: vi.fn(),
  asComplianceGateError: vi.fn(() => null),
  listComplianceRulePacks: vi.fn().mockResolvedValue([]),
  previewComplianceGate: vi.fn().mockResolvedValue({
    contract_id: 'c-1',
    contract_status: 'draft',
    rule_packs: [],
    rule_sets: ['boq_quality'],
    status: 'errors',
    score: 0,
    blocked: true,
    counts: { errors: 1, warnings: 1, passed: 0 },
    errors: [
      {
        rule_id: 'boq_quality.position_has_quantity',
        rule_name: 'Quantity',
        severity: 'error',
        message: 'Position 01 must not have zero or missing quantity',
        element_ref: '7f1c2a9e-5b1d-4e8a-9c3f-2d6b8a0e4f11',
        element_label: '01 Drywall, block B',
        suggestion: null,
      },
    ],
    warnings: [
      {
        rule_id: 'contracts.eot_claim_has_notice',
        rule_name: 'EOT notice',
        severity: 'warning',
        message: 'An extension of time claim has no notice date',
        element_ref: '0b9d4e2a-1c3f-4a5b-8d7e-6f5a4b3c2d1e',
        element_label: null,
        suggestion: null,
      },
    ],
  }),
}));

vi.mock('./ContractSigningPanel', () => ({ ContractSigningPanel: () => null }));

import { ComplianceGate } from './ComplianceGate';

describe('ComplianceGate', () => {
  it('names the line a finding points at instead of its id', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ComplianceGate contractId="c-1" contractCode="SC-001" onSigned={vi.fn()} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/01 Drywall, block B/)).toBeTruthy();
    expect(screen.queryByText(new RegExp(LINE_ID))).toBeNull();
  });

  it('prints neither a rule id nor a bare id on a finding', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ComplianceGate contractId="c-1" contractCode="SC-001" onSigned={vi.fn()} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/no notice date/)).toBeTruthy();
    expect(screen.queryByText(/boq_quality\.position_has_quantity/)).toBeNull();
    expect(screen.queryByText(/contracts\.eot_claim_has_notice/)).toBeNull();
    expect(screen.queryByText(new RegExp(OTHER_ID))).toBeNull();
  });
});
