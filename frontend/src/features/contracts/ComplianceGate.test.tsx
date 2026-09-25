// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The signature gate names the schedule line a finding is about. It used to
// print the line's id, which nobody on site can map back to a line.

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const LINE_ID = '7f1c2a9e-5b1d-4e8a-9c3f-2d6b8a0e4f11';

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
    counts: { errors: 1, warnings: 0, passed: 0 },
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
    warnings: [],
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
});
