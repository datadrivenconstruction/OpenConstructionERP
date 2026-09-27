// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every finding on the signature gate names the rule set it comes from. The
// row printed a source only when the bundle held a label for the set, and
// seven of the twenty-odd sets the compliance packs bundle had one, so a
// Romanian, Greek, Ukrainian, Hungarian or GESN finding arrived with no source.

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import en from '@/app/locales/en';

vi.mock('./api', () => ({
  signContract: vi.fn(),
  asComplianceGateError: vi.fn(() => null),
  listComplianceRulePacks: vi.fn().mockResolvedValue([]),
  previewComplianceGate: vi.fn().mockResolvedValue({
    contract_id: 'c-1',
    contract_status: 'draft',
    rule_packs: [],
    rule_sets: ['brand_new_set'],
    status: 'warnings',
    score: 50,
    blocked: false,
    counts: { errors: 0, warnings: 1, passed: 0 },
    errors: [],
    warnings: [
      {
        rule_id: 'brand_new_set.some_rule',
        rule_name: 'Some rule',
        severity: 'warning',
        message: 'A finding from a set the bundle has no name for',
        element_ref: null,
        element_label: null,
        suggestion: null,
      },
    ],
  }),
}));

vi.mock('./ContractSigningPanel', () => ({ ContractSigningPanel: () => null }));

import { ComplianceGate } from './ComplianceGate';

// The rule sets the compliance packs bundle (backend
// app/modules/contracts/compliance_packs.py), and "uk", the prefix the
// uk_statutory rules carry in their ids.
const PACK_RULE_SETS = [
  'boq_quality', 'din276', 'gaeb', 'nrm', 'uk_statutory', 'uk', 'masterformat', 'mexico', 'hungary',
  'gbt50500', 'bc3', 'gesn', 'sinapi', 'nbr', 'cpwd', 'dpgf', 'onorm', 'sekisan', 'birimfiyat',
  'romania', 'greece', 'ukraine', 'contracts',
];

describe('ComplianceGate rule set names', () => {
  it('has an English name for every rule set a compliance pack runs', () => {
    const table = en.translation as Record<string, string>;
    const missing = PACK_RULE_SETS.filter((set) => !table[`validation.rs_label_${set}`]);
    expect(missing).toEqual([]);
  });

  it('names a set the bundle does not know by its own name rather than nothing', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ComplianceGate contractId="c-1" contractCode="SC-001" onSigned={vi.fn()} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/set the bundle has no name for/)).toBeTruthy();
    expect(screen.getByText('brand new set')).toBeTruthy();
    expect(screen.queryByText(/brand_new_set\.some_rule/)).toBeNull();
  });
});
