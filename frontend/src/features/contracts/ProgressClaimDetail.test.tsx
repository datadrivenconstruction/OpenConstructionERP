// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the Gap I progress-claim bridge UI:
//   * ProgressClaimDetailPage — load/render, status-dependent buttons,
//     populate affordance only on editable claims.
//   * PopulatePreviewModal — preview render, select/deselect, empty state,
//     commit wiring.
//   * ProgressClaimLineTable — read-only vs editable rows, inline edit/save,
//     and the reads a line write makes stale.
//
// The contracts API module is fully stubbed so no network is hit.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// The global test setup (src/test/setup.ts) mocks react-router-dom with a
// useParams() that always returns {}, which would leave the detail page
// without a claimId and short-circuit its query. Restore the real router so
// the MemoryRouter/Route wrapper below actually supplies :claimId/:projectId.
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return { ...actual, useNavigate: () => vi.fn() };
});

// The global setup's i18n mock returns defaultValue but does not interpolate
// {{number}} / {{count}}. These components rely on standard i18next
// interpolation, so use an interpolation-aware t() here (matches the pattern
// used by the coordination feature tests).
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const defaultValue =
        opts && typeof opts === 'object' && 'defaultValue' in opts
          ? (opts.defaultValue as string)
          : key;
      if (!opts) return defaultValue;
      return defaultValue.replace(/\{\{(\w+)\}\}/g, (_, name) =>
        String(opts[name] ?? ''),
      );
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock('./api', () => ({
  getProgressClaim: vi.fn(),
  listClaimLines: vi.fn(),
  submitClaim: vi.fn(),
  approveClaim: vi.fn(),
  certifyClaim: vi.fn(),
  rejectClaim: vi.fn(),
  markClaimPaid: vi.fn(),
  populateClaimPreview: vi.fn(),
  commitClaimLines: vi.fn(),
  updateClaimLine: vi.fn(),
  // Billing a line by hand, and the schedule of values it is picked from.
  createClaimLine: vi.fn(),
  listContractLines: vi.fn(),
  // The contract says which way the claim invoice goes.
  getContract: vi.fn().mockResolvedValue({ counterparty_type: 'client' }),
  // The submission check under the header, and the G702 it reads line 7's
  // basis from on AIA projects.
  getClaimValidation: vi.fn(),
  getAiaApplication: vi.fn(),
}));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel) => sel({ addToast: vi.fn() }),
}));

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (sel) => sel({ userRole: 'manager' }),
}));

import * as api from './api';
import { ProgressClaimDetailPage } from './ProgressClaimDetailPage';
import { ClaimPeriod } from './ClaimPeriod';
import { PopulatePreviewModal } from './PopulatePreviewModal';
import { ProgressClaimLineTable } from './ProgressClaimLineTable';
import {
  claimKey,
  claimLinesKey,
  aiaApplicationKey,
  CLAIMS_LIST_KEY,
} from './claimQueries';

const CLAIM_ID = '00000000-0000-0000-0000-0000000000c1';
const PROJECT_ID = '00000000-0000-0000-0000-0000000000p1';

function claim(overrides = {}) {
  return {
    id: CLAIM_ID,
    contract_id: 'ctr-1',
    claim_number: 'PC-0001',
    period_start: '2026-05-01',
    period_end: '2026-05-31',
    claim_date: null,
    gross_amount: '400',
    retention_amount: '20',
    prior_claims_total: '0',
    net_due: '380',
    status: 'draft',
    submitted_at: null,
    approved_at: null,
    paid_at: null,
    currency: 'USD',
    metadata: {},
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

function previewItem(overrides = {}) {
  return {
    contract_line_id: 'line-1',
    contract_line_code: 'L1',
    contract_line_description: 'Concrete',
    boq_position_id: 'pos-1',
    unit: 'm3',
    contract_quantity: '10',
    contract_line_value: '1000',
    observed_pct: '40',
    period_label: '2026-W22',
    recorded_at: '2026-05-30T00:00:00Z',
    period_completed_qty: '4',
    period_completed_value: '400',
    cumulative_completed_value: '400',
    ...overrides,
  };
}

function claimLine(overrides = {}) {
  return {
    id: 'cl-1',
    progress_claim_id: CLAIM_ID,
    contract_line_id: 'line-1',
    period_completed_qty: '4',
    period_completed_value: '400',
    period_completed_pct: '40',
    cumulative_completed_value: '400',
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}/contracts/claims/${CLAIM_ID}`]}>
        <Routes>
          <Route
            path="/projects/:projectId/contracts/claims/:claimId"
            element={<ProgressClaimDetailPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderModal(props = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PopulatePreviewModal
          claimId={CLAIM_ID}
          currency="USD"
          onClose={vi.fn()}
          {...props}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function report(overrides = {}) {
  return {
    claim_id: CLAIM_ID,
    status: 'passed',
    score: 1,
    summary: {},
    rule_sets: ['pay_application'],
    unsupported_rule_sets: [],
    errors: [],
    warnings: [],
    ...overrides,
  };
}

function sovLine(overrides = {}) {
  return {
    id: 'line-1',
    contract_id: 'ctr-1',
    parent_line_id: null,
    code: 'A1',
    description: 'Concrete',
    scope_section: null,
    line_type: 'work',
    unit: 'm3',
    quantity: '10',
    unit_rate: '100',
    total_value: '1000',
    order_index: 0,
    metadata: {},
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getClaimValidation.mockResolvedValue(report());
  api.listContractLines.mockResolvedValue([]);
});

describe('ProgressClaimDetailPage', () => {
  it('loads and renders the claim header + totals', async () => {
    api.getProgressClaim.mockResolvedValue(claim());
    api.listClaimLines.mockResolvedValue([]);
    renderDetail();
    // The claim number renders in both the breadcrumb and the heading, so
    // assert on at least one match rather than a unique element.
    await waitFor(() => expect(screen.getAllByText(/PC-0001/).length).toBeGreaterThan(0));
    expect(screen.getByTestId('progress-claim-detail')).toBeTruthy();
  });

  it('shows the Populate button on a draft claim', async () => {
    api.getProgressClaim.mockResolvedValue(claim({ status: 'draft' }));
    api.listClaimLines.mockResolvedValue([]);
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('populate-button')).toBeTruthy());
  });

  it('hides the Populate button on a certified claim', async () => {
    api.getProgressClaim.mockResolvedValue(claim({ status: 'certified' }));
    api.listClaimLines.mockResolvedValue([]);
    renderDetail();
    await waitFor(() => expect(screen.getAllByText(/PC-0001/).length).toBeGreaterThan(0));
    expect(screen.queryByTestId('populate-button')).toBeNull();
  });

  it('shows Submit on draft and Approve/Reject on submitted', async () => {
    api.getProgressClaim.mockResolvedValue(claim({ status: 'submitted' }));
    api.listClaimLines.mockResolvedValue([]);
    renderDetail();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Approve/i })).toBeTruthy(),
    );
    expect(screen.getByRole('button', { name: /Reject/i })).toBeTruthy();
    expect(screen.queryByText(/^Submit$/i)).toBeNull();
  });

  it('opens the populate modal when the button is clicked', async () => {
    api.getProgressClaim.mockResolvedValue(claim({ status: 'draft' }));
    api.listClaimLines.mockResolvedValue([]);
    api.populateClaimPreview.mockResolvedValue({
      claim_id: CLAIM_ID,
      contract_id: 'ctr-1',
      currency: 'USD',
      items: [previewItem()],
      skipped_unlinked: 0,
      skipped_no_progress: 0,
      skipped_foreign_currency: 0,
      gross: '400',
      retention: '20',
      prior_claims_total: '0',
      net_due: '380',
    });
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('populate-button')).toBeTruthy());
    fireEvent.click(screen.getByTestId('populate-button'));
    await waitFor(() =>
      expect(screen.getByTestId('populate-preview-table')).toBeTruthy(),
    );
  });

  it('shows the submission check and leaves Submit to the server gate', async () => {
    api.getProgressClaim.mockResolvedValue(claim({ status: 'draft' }));
    api.listClaimLines.mockResolvedValue([]);
    api.getClaimValidation.mockResolvedValue(
      report({
        status: 'errors',
        errors: [
          {
            rule_id: 'pay_application.line_overbilled',
            rule_name: 'No line is billed beyond its scheduled value',
            severity: 'error',
            passed: false,
            message: 'Line L1 is billed 1,200.00 USD to date against a scheduled value of 1,000.00 USD.',
            element_ref: 'line-1',
            suggestion: 'Reduce the billed amount on the line.',
            details: {},
          },
        ],
      }),
    );
    renderDetail();

    const panel = await screen.findByTestId('claim-validation-panel');
    await waitFor(() =>
      expect(within(panel).getByText(/Line L1 is billed/)).toBeTruthy(),
    );
    // The panel reports; it does not decide. Submit stays pressable, and the
    // server refuses it with the same report.
    const submit = screen.getByRole('button', { name: /^Submit$/i });
    expect(submit.hasAttribute('disabled')).toBe(false);
  });

  it('links back to the claims tab, from the arrow and from the breadcrumb', async () => {
    api.getProgressClaim.mockResolvedValue(claim());
    api.listClaimLines.mockResolvedValue([]);
    renderDetail();

    // The bare register opens on its Contracts tab, one click away from the
    // list the claim was opened from.
    const claimsTab = `/projects/${PROJECT_ID}/contracts?tab=claims`;
    const back = await screen.findByRole('link', { name: 'Back' });
    expect(back.getAttribute('href')).toBe(claimsTab);
    expect(screen.getByRole('link', { name: 'Contracts' }).getAttribute('href')).toBe(claimsTab);
  });

  it('prints the parsed period in the header, as the claims list does', async () => {
    const period = {
      period_start: 'first of May',
      period_end: 'end of May',
      period_from: '2026-05-01',
      period_to: '2026-05-31',
    };
    api.getProgressClaim.mockResolvedValue(claim(period));
    api.listClaimLines.mockResolvedValue([]);
    renderDetail();

    const header = await screen.findByTestId('claim-period');
    const { container } = render(<ClaimPeriod claim={period} />);
    expect(header.textContent).toBe(container.textContent);
    expect(header.textContent).not.toContain('first of May');
  });

  it('offers no line edits once the claim has left draft', async () => {
    api.getProgressClaim.mockResolvedValue(claim({ status: 'submitted' }));
    api.listClaimLines.mockResolvedValue([claimLine()]);
    renderDetail();

    // The breakdown a submitted claim was billed on is not the screen's to
    // change. The claim's stored gross, retention and net were computed from
    // it, the AR invoice is booked on those, and the next claim's "previous"
    // column is read from them.
    await waitFor(() => expect(screen.getByTestId('claim-lines-locked')).toBeTruthy());
    expect(screen.queryByTestId('populate-button')).toBeNull();
    expect(screen.queryByText(/^Edit$/i)).toBeNull();
    // A rejected claim stays rejected, so the way to corrected figures is a
    // new draft claim; say so rather than leave the reader looking for it.
    expect(screen.getByTestId('claim-lines-locked').textContent).toMatch(/new draft claim/i);
  });

  it.each(['paid', 'rejected', 'certified'])(
    'does not tell a %s claim to get itself rejected',
    async (status) => {
      api.getProgressClaim.mockResolvedValue(claim({ status }));
      api.listClaimLines.mockResolvedValue([claimLine()]);
      renderDetail();

      // Reject is offered on a submitted claim and nowhere else, so on these
      // the hint would be an instruction nobody can follow - and on a claim
      // already rejected it would be nonsense.
      const note = await screen.findByTestId('claim-lines-locked');
      expect(note.textContent).not.toMatch(/new draft claim/i);
    },
  );

  it('lets a hand-written contract be billed, with no progress to populate from', async () => {
    // "Populate from progress" needs the schedule of values tied to bid
    // positions and observations from site. A contract typed in by hand has
    // neither, and until now that left its claim with no lines and no way to
    // add one - the small job could not raise a payment application at all.
    api.getProgressClaim.mockResolvedValue(claim({ status: 'draft' }));
    api.listClaimLines.mockResolvedValue([]);
    api.listContractLines.mockResolvedValue([sovLine()]);
    api.createClaimLine.mockResolvedValue(claimLine());
    renderDetail();

    fireEvent.click(await screen.findByTestId('claim-add-line'));
    fireEvent.change(screen.getByLabelText('Line'), { target: { value: 'line-1' } });
    fireEvent.change(screen.getByLabelText('% complete'), { target: { value: '40' } });
    fireEvent.change(screen.getByLabelText('Period value'), { target: { value: '400' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    await waitFor(() => expect(api.createClaimLine).toHaveBeenCalledTimes(1));
    expect(api.createClaimLine).toHaveBeenCalledWith({
      progress_claim_id: CLAIM_ID,
      contract_line_id: 'line-1',
      period_completed_pct: 40,
      period_completed_value: 400,
    });
  });

  it('says where to start when the contract has no lines to bill', async () => {
    api.getProgressClaim.mockResolvedValue(claim({ status: 'draft' }));
    api.listClaimLines.mockResolvedValue([]);
    api.listContractLines.mockResolvedValue([]);
    renderDetail();

    // Nothing to pick from is a different problem from nothing to populate
    // from, and it is fixed on the contract, not here.
    await waitFor(() => expect(screen.getAllByText(/PC-0001/).length).toBeGreaterThan(0));
    expect(screen.queryByTestId('claim-add-line')).toBeNull();
    expect(screen.getByText(/no schedule of values/i)).toBeTruthy();
  });

  it('does not offer to bill a line the claim already carries', async () => {
    api.getProgressClaim.mockResolvedValue(claim({ status: 'draft' }));
    api.listClaimLines.mockResolvedValue([claimLine({ contract_line_id: 'line-1' })]);
    api.listContractLines.mockResolvedValue([sovLine()]);
    renderDetail();

    // One claim line per schedule-of-values line; the row already there is
    // edited instead, which is what the inline editor is for.
    await waitFor(() => expect(screen.getByTestId('claim-line-table')).toBeTruthy());
    expect(screen.queryByTestId('claim-add-line')).toBeNull();
  });

  it('does not run the submission check on a certified claim', async () => {
    api.getProgressClaim.mockResolvedValue(claim({ status: 'certified' }));
    api.listClaimLines.mockResolvedValue([]);
    renderDetail();
    await waitFor(() => expect(screen.getAllByText(/PC-0001/).length).toBeGreaterThan(0));
    expect(screen.queryByTestId('claim-validation-panel')).toBeNull();
    expect(api.getClaimValidation).not.toHaveBeenCalled();
  });
});

describe('PopulatePreviewModal', () => {
  it('renders preview items with checkboxes and a selected summary', async () => {
    api.populateClaimPreview.mockResolvedValue({
      claim_id: CLAIM_ID,
      contract_id: 'ctr-1',
      currency: 'USD',
      items: [previewItem(), previewItem({ contract_line_id: 'line-2', contract_line_code: 'L2' })],
      skipped_unlinked: 0,
      skipped_no_progress: 0,
      skipped_foreign_currency: 0,
      gross: '800',
      retention: '40',
      prior_claims_total: '0',
      net_due: '760',
    });
    renderModal();
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.length).toBe(2);
    expect(screen.getByTestId('populate-selected-summary').textContent).toMatch(/2 selected/);
  });

  it('deselecting a row drops it from the selected count', async () => {
    api.populateClaimPreview.mockResolvedValue({
      claim_id: CLAIM_ID,
      contract_id: 'ctr-1',
      currency: 'USD',
      items: [previewItem(), previewItem({ contract_line_id: 'line-2' })],
      skipped_unlinked: 0,
      skipped_no_progress: 0,
      skipped_foreign_currency: 0,
      gross: '800',
      retention: '40',
      prior_claims_total: '0',
      net_due: '760',
    });
    renderModal();
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    expect(screen.getByTestId('populate-selected-summary').textContent).toMatch(/1 selected/);
  });

  it('shows the empty alert and disables Commit when no items', async () => {
    api.populateClaimPreview.mockResolvedValue({
      claim_id: CLAIM_ID,
      contract_id: 'ctr-1',
      currency: 'USD',
      items: [],
      skipped_unlinked: 2,
      skipped_no_progress: 0,
      skipped_foreign_currency: 0,
      gross: '0',
      retention: '0',
      prior_claims_total: '0',
      net_due: '0',
    });
    renderModal();
    await waitFor(() => expect(screen.getByTestId('populate-empty')).toBeTruthy());
    const commit = screen.getByText(/Commit lines/i).closest('button');
    expect(commit?.disabled).toBe(true);
  });

  it('commits the selected lines and closes', async () => {
    const onClose = vi.fn();
    const onCommitted = vi.fn();
    api.populateClaimPreview.mockResolvedValue({
      claim_id: CLAIM_ID,
      contract_id: 'ctr-1',
      currency: 'USD',
      items: [previewItem()],
      skipped_unlinked: 0,
      skipped_no_progress: 0,
      skipped_foreign_currency: 0,
      gross: '400',
      retention: '20',
      prior_claims_total: '0',
      net_due: '380',
    });
    api.commitClaimLines.mockResolvedValue(claim());
    renderModal({ onClose, onCommitted });
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeTruthy());
    fireEvent.click(screen.getByText(/Commit lines/i));
    await waitFor(() => expect(api.commitClaimLines).toHaveBeenCalledTimes(1));
    expect(api.commitClaimLines).toHaveBeenCalledWith(CLAIM_ID, [
      { contract_line_id: 'line-1', period_completed_pct: 40, period_completed_value: 400 },
    ]);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe('ProgressClaimLineTable', () => {
  const line = {
    id: 'cl-1',
    progress_claim_id: CLAIM_ID,
    contract_line_id: 'line-1',
    period_completed_qty: '4',
    period_completed_value: '400',
    period_completed_pct: '40',
    cumulative_completed_value: '400',
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
  };

  function renderTable(editable) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <ProgressClaimLineTable
          claimId={CLAIM_ID}
          lines={[line]}
          currency="USD"
          editable={editable}
        />
      </QueryClientProvider>,
    );
  }

  it('is read-only when the claim is not editable (no Edit button)', () => {
    renderTable(false);
    expect(screen.queryByText(/^Edit$/i)).toBeNull();
  });

  it('exposes an inline edit → save flow when editable', async () => {
    api.updateClaimLine.mockResolvedValue(line);
    renderTable(true);
    fireEvent.click(screen.getByText(/^Edit$/i));
    const row = within(screen.getByTestId('claim-line-table'));
    const pctInput = row.getByLabelText(/% complete/i);
    fireEvent.change(pctInput, { target: { value: '55' } });
    fireEvent.click(screen.getByText(/^Save$/i));
    await waitFor(() => expect(api.updateClaimLine).toHaveBeenCalledTimes(1));
    expect(api.updateClaimLine).toHaveBeenCalledWith(
      'cl-1',
      expect.objectContaining({ period_completed_pct: 55 }),
    );
  });

  it('re-reads the claim, its lines, the G702 and the register after a save', async () => {
    api.updateClaimLine.mockResolvedValue(line);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidated = vi.spyOn(client, 'invalidateQueries');
    render(
      <QueryClientProvider client={client}>
        <ProgressClaimLineTable
          claimId={CLAIM_ID}
          lines={[line]}
          currency="USD"
          editable
        />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByText(/^Edit$/i));
    fireEvent.click(screen.getByText(/^Save$/i));
    await waitFor(() => expect(api.updateClaimLine).toHaveBeenCalledTimes(1));

    // A line write moves the claim's stored gross, retention and net, the
    // G702 face drawn from the same lines, and the amount in the register's
    // row. Keeping any of them on screen is showing money from before the
    // write - which is the figure an AR invoice would be booked from.
    const keys = invalidated.mock.calls.map((c) => JSON.stringify(c[0].queryKey));
    expect(keys).toContain(JSON.stringify(claimKey(CLAIM_ID)));
    expect(keys).toContain(JSON.stringify(claimLinesKey(CLAIM_ID)));
    expect(keys).toContain(JSON.stringify(aiaApplicationKey(CLAIM_ID)));
    expect(keys).toContain(JSON.stringify(CLAIMS_LIST_KEY));
  });
});
