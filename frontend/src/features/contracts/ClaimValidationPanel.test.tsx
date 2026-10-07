// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Component tests for <ClaimValidationPanel>.
//
// The panel exists because a claim's findings used to reach the user only as a
// 422 toast on Submit, three errors at most and warnings never. What is worth
// pinning: both lists render with the server's own words, the light follows
// the findings, the panel disables nothing (Submit is the server's call), the
// report refreshes whenever the claim does, and the note about a rebuilt G702
// line 7 appears only when the application says so.
//
// The i18n mock in src/test/setup.ts returns the defaultValue, so the English
// copy below is what renders here.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  getClaimValidation: vi.fn(),
  getAiaApplication: vi.fn(),
  getPaymentApplication: vi.fn(),
}));

import * as api from './api';
import { ClaimValidationPanel } from './ClaimValidationPanel';

const CLAIM_ID = '00000000-0000-0000-0000-0000000000c1';

const getReportMock = vi.mocked(api.getClaimValidation);
const getAiaMock = vi.mocked(api.getAiaApplication);
const getPaymentMock = vi.mocked(api.getPaymentApplication);

function finding(overrides: Partial<api.ClaimValidationFinding> = {}): api.ClaimValidationFinding {
  return {
    rule_id: 'pay_application.line_overbilled',
    rule_name: 'No line is billed beyond its scheduled value',
    severity: 'error',
    passed: false,
    message: 'Line L1 is billed 1,200.00 USD to date against a scheduled value of 1,000.00 USD.',
    element_ref: 'line-1',
    suggestion: 'Reduce the billed amount on the line.',
    details: {},
    ...overrides,
  };
}

const OVERLAP = finding({
  rule_id: 'pay_application.period_overlap',
  severity: 'warning',
  message: 'The period of PC-0002 overlaps the period of PC-0001.',
  element_ref: CLAIM_ID,
  suggestion: 'Move the period so it starts after the previous claim ends.',
});

function report(overrides: Partial<api.ClaimValidationReport> = {}): api.ClaimValidationReport {
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

function aiaApplication(basis: string | null): api.AIAApplication {
  return {
    claim_id: CLAIM_ID,
    contract_id: 'ctr-1',
    project_id: 'prj-1',
    application_number: '2',
    currency: 'USD',
    claim_status: 'draft',
    retainage_percent: '10',
    summary: {
      original_contract_sum: '1000',
      change_orders_net: '0',
      contract_sum_to_date: '1000',
      total_completed_stored: '400',
      retainage: '40',
      total_earned_less_retainage: '360',
      previous_certificates_total: '180',
      previous_certificates_basis: basis,
      current_payment_due: '180',
      balance_to_finish: '640',
    },
    lines: [],
    certification: {},
  };
}

function renderPanel(
  props: Partial<{ awaitingSubmit: boolean; aiaEligible: boolean }> = {},
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  const view = render(
    <QueryClientProvider client={client}>
      <ClaimValidationPanel claimId={CLAIM_ID} awaitingSubmit aiaEligible={false} {...props} />
      <button type="button">Submit</button>
    </QueryClientProvider>,
  );
  return { client, ...view };
}

describe('ClaimValidationPanel', () => {
  beforeEach(() => {
    // Reset, not clear: a queued mockResolvedValueOnce a test did not consume
    // would otherwise answer the next test's first request.
    vi.resetAllMocks();
    getReportMock.mockResolvedValue(report());
    getPaymentMock.mockResolvedValue(aiaApplication('snapshot'));
  });

  it('lists errors and warnings in the words the server sent', async () => {
    getReportMock.mockResolvedValue(report({ status: 'errors', errors: [finding()], warnings: [OVERLAP] }));
    renderPanel();

    const panel = await screen.findByTestId('claim-validation-panel');
    expect(panel.getAttribute('data-light')).toBe('errors');
    expect(screen.getByTestId('claim-validation-state')).toHaveTextContent('Errors found');

    const errors = screen.getByTestId('claim-validation-errors');
    expect(within(errors).getByText(finding().message)).toBeInTheDocument();
    expect(within(errors).getByText('Reduce the billed amount on the line.')).toBeInTheDocument();
    const warnings = screen.getByTestId('claim-validation-warnings');
    expect(within(warnings).getByText(OVERLAP.message)).toBeInTheDocument();

    expect(within(panel).getByText('Errors 1')).toBeInTheDocument();
    expect(within(panel).getByText('Warnings 1')).toBeInTheDocument();
    expect(
      within(panel).getByText('Errors block Submit. Warnings do not: read them, then submit if the claim is right.'),
    ).toBeInTheDocument();
    // The English rule name is not what the reader is told; the message is.
    expect(within(panel).queryByText(finding().rule_name)).toBeNull();
  });

  it('turns amber on warnings alone, and says they do not block', async () => {
    getReportMock.mockResolvedValue(report({ status: 'warnings', warnings: [OVERLAP] }));
    renderPanel();

    const panel = await screen.findByTestId('claim-validation-panel');
    expect(panel.getAttribute('data-light')).toBe('warnings');
    expect(screen.getByTestId('claim-validation-state')).toHaveTextContent('Warnings only');
    expect(screen.queryByTestId('claim-validation-errors')).toBeNull();
  });

  it('tells a clean report from one where nothing ran', async () => {
    const { unmount } = renderPanel();
    expect(await screen.findByTestId('claim-validation-state')).toHaveTextContent('No findings');
    unmount();

    getReportMock.mockResolvedValue(report({ status: 'unsupported', score: null }));
    renderPanel();
    expect(await screen.findByTestId('claim-validation-state')).toHaveTextContent('Nothing was checked');
  });

  it('disables nothing by itself', async () => {
    getReportMock.mockResolvedValue(report({ status: 'errors', errors: [finding()] }));
    renderPanel();

    const panel = await screen.findByTestId('claim-validation-panel');
    await within(panel).findByText(finding().message);
    // Blocking is the server gate's decision. A second copy of it here could
    // only drift from the one that actually refuses the claim.
    expect(screen.getByRole('button', { name: 'Submit' })).toBeEnabled();
    expect(panel.querySelectorAll('[disabled], [aria-disabled="true"]')).toHaveLength(0);
  });

  it('refetches whenever the claim is invalidated', async () => {
    getReportMock
      .mockResolvedValueOnce(report({ status: 'errors', errors: [finding()] }))
      .mockResolvedValueOnce(report());
    const { client } = renderPanel();
    expect(await screen.findByTestId('claim-validation-state')).toHaveTextContent('Errors found');

    // What the page, the line table, populate and the roll-up already call
    // after every change. The report sits under this key, so it follows.
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['contracts', 'claim', CLAIM_ID] });
    });

    await waitFor(() => expect(screen.getByTestId('claim-validation-state')).toHaveTextContent('No findings'));
    expect(getReportMock).toHaveBeenCalledTimes(2);
    expect(getReportMock).toHaveBeenLastCalledWith(CLAIM_ID);
  });

  it('says so when it cannot run, and can try again', async () => {
    getReportMock.mockRejectedValueOnce(new Error('boom'));
    renderPanel();

    expect(
      await screen.findByText('Could not run the submission check. Submit still runs it on the server.'),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('claim-validation-recheck'));
    expect(await screen.findByTestId('claim-validation-state')).toHaveTextContent('No findings');
  });

  it('words the hint for a claim already submitted', async () => {
    renderPanel({ awaitingSubmit: false });
    expect(
      await screen.findByText('Checked as the claim stands now, including edits made after it was submitted.'),
    ).toBeInTheDocument();
  });

  it('notes a rebuilt G702 line 7 only when the application says it is rebuilt', async () => {
    getAiaMock.mockResolvedValue(aiaApplication('reconstructed'));
    const { unmount } = renderPanel({ aiaEligible: true });
    expect(await screen.findByTestId('claim-validation-reconstructed')).toHaveTextContent(
      'Previous certified amounts are rebuilt from earlier claims',
    );
    unmount();

    // Seeded, so the application is on hand at the first render and an absent
    // note cannot be a note that simply has not arrived yet.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(['contracts', 'aia-application', CLAIM_ID], aiaApplication('snapshot'));
    renderPanel({ aiaEligible: true }, client);
    await screen.findByTestId('claim-validation-state');
    expect(screen.queryByTestId('claim-validation-reconstructed')).toBeNull();
  });

  it('does not ask for a G702 outside the AIA countries', async () => {
    getPaymentMock.mockResolvedValue(aiaApplication('reconstructed'));
    renderPanel({ aiaEligible: false });
    await screen.findByTestId('claim-validation-state');
    expect(getAiaMock).not.toHaveBeenCalled();
    expect(getPaymentMock).toHaveBeenCalledWith(CLAIM_ID);
    expect(await screen.findByTestId('claim-validation-reconstructed')).toHaveTextContent(
      'Previous certified amounts are rebuilt from earlier claims',
    );
  });

  it('refreshes the common certificate basis when the claim changes', async () => {
    getPaymentMock.mockResolvedValueOnce(aiaApplication('reconstructed'));
    const { client } = renderPanel();
    await screen.findByTestId('claim-validation-reconstructed');
    await act(async () => {
      await client.invalidateQueries({ queryKey: ['contracts', 'claim', CLAIM_ID] });
    });
    await waitFor(() => expect(screen.queryByTestId('claim-validation-reconstructed')).toBeNull());
    expect(getPaymentMock).toHaveBeenCalledTimes(2);
  });
});
