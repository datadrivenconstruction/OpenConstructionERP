// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The completeness list, rendered over a finding pair the old key could not
// tell apart.
//
// The list keyed on rule id and element reference, with the loop index as a
// fallback. The fallback is `element_ref ?? i`, so it engages only when the
// reference is null, and an empty string is not null: `'' ?? i` is `''`. The
// EOT rule stamps `element_ref` with `str(claim.get("id", ""))`, so two claims
// that reach it without an id are two findings carrying one rule id and one
// element reference, and React saw two children with one key.
//
// The pair below is that shape, with the backend's own message and suggestion
// text. It is the reachable case; the general one is any rule that reports
// more than one thing about a single element, which the engine has elsewhere
// (`schedule_quality.negative_lag` files one finding per relationship, all
// stamped with the successor activity).
//
// The helper that fixes it has its own tests. This file exists because those
// tests cannot say whether the list actually uses it, and because a key defect
// is invisible in the DOM: React renders both rows on first mount and drops one
// later, on an update the test never performs. The console warning is the only
// contemporaneous signal, so the second test proves the spy can hear it before
// the first test's silence is allowed to mean anything.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  getSovStatus: vi.fn(),
  getContractCompleteness: vi.fn(),
  getEotSummary: vi.fn(),
  getFinalAccountChecklist: vi.fn(),
  getGainsharePreview: vi.fn(),
  getSecurityCoverage: vi.fn(),
  listContractLines: vi.fn(),
}));

import { ContractAnalyticsPanels } from './ContractAnalyticsPanels';
import { findingKeys } from './findingKeys';
import * as api from './api';
import type { CompletenessFinding, CompletenessReport } from './api';

const CONTRACT_ID = '6f1c9d80-0f4b-4a5d-9c2a-3f9b6f2f77aa';

/** Two EOT findings that reached the rule without an id: one rule id, one ref. */
const COLLIDING_FINDINGS: CompletenessFinding[] = [
  {
    rule_id: 'contracts.eot_days_valid',
    rule_name: 'EOT granted days within claimed days',
    severity: 'error',
    passed: false,
    message: 'EOT 3 grants 9 day(s) but only 4 claimed',
    element_ref: '',
    suggestion: 'Reduce granted days to at most the claimed days',
  },
  {
    rule_id: 'contracts.eot_days_valid',
    rule_name: 'EOT granted days within claimed days',
    severity: 'error',
    passed: false,
    message: 'EOT 5 grants 20 day(s) but only 12 claimed',
    element_ref: '',
    suggestion: 'Reduce granted days to at most the claimed days',
  },
];

function report(): CompletenessReport {
  return {
    contract_id: CONTRACT_ID,
    status: 'errors',
    score: 0.16,
    summary: {
      status: 'errors',
      score: 0.16,
      counts: { total: 2, passed: 0, errors: 2, warnings: 0, infos: 0, engine_errors: 0 },
    },
    errors: COLLIDING_FINDINGS,
    warnings: [],
  };
}

function renderPanels() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ContractAnalyticsPanels contractId={CONTRACT_ID} currency="EUR" />
    </QueryClientProvider>,
  );
}

// Captured rather than read back off the spy object: `ReturnType<typeof
// vi.spyOn>` resolves through an overloaded generic signature, and this file is
// compiled by `tsc -b` along with the rest of src.
let consoleErrors: unknown[][] = [];

/** Console errors React raises for duplicate keys, and nothing else. */
function duplicateKeyWarnings(): unknown[][] {
  return consoleErrors.filter((args) =>
    args.some((a) => typeof a === 'string' && /two children with the same key/i.test(a)),
  );
}

beforeEach(() => {
  consoleErrors = [];
  vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    consoleErrors.push(args);
  });
  // The five panels this file is not about: let them land in their error state
  // rather than invent shapes for them.
  const unrelated = [
    api.getSovStatus,
    api.getEotSummary,
    api.getFinalAccountChecklist,
    api.getGainsharePreview,
    api.getSecurityCoverage,
    api.listContractLines,
  ];
  for (const fn of unrelated) {
    vi.mocked(fn).mockRejectedValue(new Error('not part of this test'));
  }
  vi.mocked(api.getContractCompleteness).mockResolvedValue(report());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CompletenessPanel finding list', () => {
  it('draws both findings without a duplicate-key warning', async () => {
    renderPanels();

    expect(await screen.findByText('EOT 3 grants 9 day(s) but only 4 claimed')).toBeInTheDocument();
    expect(screen.getByText('EOT 5 grants 20 day(s) but only 12 claimed')).toBeInTheDocument();
    expect(duplicateKeyWarnings()).toEqual([]);
  });

  it('would have warned on the key this list used to build', async () => {
    // The control. Without it, the assertion above passes on a build where
    // React stopped warning, where the spy is attached to the wrong console, or
    // where the panel silently rendered nothing at all.
    const Naive = ({ findings }: { findings: CompletenessFinding[] }) => (
      <ul>
        {findings.map((f, i) => (
          <li key={`${f.rule_id}-${f.element_ref ?? i}`}>{f.message}</li>
        ))}
      </ul>
    );
    render(<Naive findings={COLLIDING_FINDINGS} />);

    await waitFor(() => expect(duplicateKeyWarnings().length).toBeGreaterThan(0));
  });

  it('keys the two findings apart', () => {
    // The value itself, so a failure says which key was built rather than only
    // that React was unhappy about one of them.
    expect(findingKeys(COLLIDING_FINDINGS)).toEqual([
      'contracts.eot_days_valid||EOT 3 grants 9 day(s) but only 4 claimed',
      'contracts.eot_days_valid||EOT 5 grants 20 day(s) but only 12 claimed',
    ]);
  });
});
