// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for <SubRollupPanel>.
//
// The panel records a person's choices (include, exclude, re-map a line) and
// never writes the claim's lines, so what is worth pinning is:
//
//   * the include call carries exactly the pay applications that were ticked;
//   * a refusal is shown in the claim page's own words, keyed on the code the
//     server sends, not as the raw server sentence;
//   * a claim past editing offers no include, exclude or re-map at all;
//   * a pay-application line can only be re-mapped onto a billable SOV line,
//     never a grouping line other lines hang under;
//   * the three chips say what the rollup says, including "not checked" when
//     the claim has no period end, which is not the same as "valid";
//   * a missing module (404) removes the panel instead of breaking the page;
//   * the subs' suggestion opens the shared preview and commits through the
//     claim's own commit route, with the exact values it was given.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/features/subcontractors/api', () => ({
  getClaimSubRollup: vi.fn(),
  includePayApplicationsInClaim: vi.fn(),
  excludePayApplicationFromClaim: vi.fn(),
  updatePaymentApplicationLine: vi.fn(),
  listPaymentApplicationLines: vi.fn(),
  listWorkPackages: vi.fn(),
  getSuggestedClaimLines: vi.fn(),
}));

vi.mock('./api', () => ({
  listContractLines: vi.fn(),
  populateClaimPreview: vi.fn(),
  commitClaimLines: vi.fn(),
}));

const addToast = vi.fn();
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: typeof addToast }) => unknown) => sel({ addToast }),
}));

import { SubRollupPanel } from './SubRollupPanel';
import * as subsApi from '@/features/subcontractors/api';
import * as contractsApi from './api';
import type { ClaimSubRollup, SubRollupPayApp } from '@/features/subcontractors/api';
import type { ContractLine } from './api';
import { ApiError } from '@/shared/lib/api';

const rollupMock = vi.mocked(subsApi.getClaimSubRollup);
const includeMock = vi.mocked(subsApi.includePayApplicationsInClaim);
const excludeMock = vi.mocked(subsApi.excludePayApplicationFromClaim);
const remapMock = vi.mocked(subsApi.updatePaymentApplicationLine);
const linesMock = vi.mocked(contractsApi.listContractLines);
const payAppLinesMock = vi.mocked(subsApi.listPaymentApplicationLines);
const packagesMock = vi.mocked(subsApi.listWorkPackages);
const suggestMock = vi.mocked(subsApi.getSuggestedClaimLines);
const populateMock = vi.mocked(contractsApi.populateClaimPreview);
const commitMock = vi.mocked(contractsApi.commitClaimLines);

function payApp(over: Partial<SubRollupPayApp> = {}): SubRollupPayApp {
  return {
    payment_application_id: 'pa-1',
    application_number: 'PA-1',
    agreement_id: 'ag-1',
    agreement_title: 'Concrete subcontract',
    subcontractor_id: 'sub-1',
    subcontractor_name: 'Example Concrete',
    status: 'finance_approved',
    period_start: '2026-04-01',
    period_end: '2026-04-30',
    currency: 'USD',
    gross_amount: '2000.00',
    net_amount: '1800.00',
    claimed_amount: '2000.00',
    certified_amount: '2000.00',
    approved_amount: '2000.00',
    line_count: 1,
    progress_claim_id: null,
    in_period: true,
    requires_lien_waiver: true,
    waiver: {
      state: 'conditional',
      amount_covered: '1800.00',
      covers_net: true,
      through_date: '2026-04-30',
      through_date_basis: 'through_date',
    },
    certificates_ok: true,
    certificate_findings: [],
    foreign_currency: false,
    ...over,
  };
}

function rollup(over: Partial<ClaimSubRollup> = {}): ClaimSubRollup {
  return {
    claim_id: 'claim-1',
    contract_id: 'ct-1',
    project_id: 'p-1',
    claim_status: 'draft',
    currency: 'USD',
    period_from: '2026-04-01',
    period_to: '2026-04-30',
    period_matching: 'dates',
    as_of: '2026-04-30',
    lines: [],
    included: [],
    candidates: [],
    unmapped_lines: [],
    agreements: [
      {
        agreement_id: 'ag-1',
        title: 'Concrete subcontract',
        subcontractor_id: 'sub-1',
        subcontractor_name: 'Example Concrete',
        prime_contract_id: 'ct-1',
        resolution: 'explicit',
      },
    ],
    requirements: { certificate_types: ['insurance', 'license'], lien_waiver_required: false, source: 'fallback', reference: null },
    skipped_foreign_currency: 0,
    sub_period_approved_total: '0',
    gc_period_total: '0',
    ...over,
  };
}

function sovLine(over: Partial<ContractLine>): ContractLine {
  return {
    id: 'ln-x',
    contract_id: 'ct-1',
    parent_line_id: null,
    code: '',
    description: '',
    scope_section: null,
    line_type: 'item' as ContractLine['line_type'],
    unit: null,
    quantity: 0,
    unit_rate: 0,
    total_value: 0,
    order_index: 0,
    metadata: {},
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    ...over,
  };
}

function renderPanel(editable = true) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SubRollupPanel claimId="claim-1" contractId="ct-1" currency="USD" editable={editable} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SubRollupPanel', () => {
  it('overrides one pay-application line, and the package default clears the override', async () => {
    rollupMock.mockResolvedValue(rollup({ included: [payApp({ progress_claim_id: 'claim-1' })] }));
    payAppLinesMock.mockResolvedValue([
      {
        id: 'pal-1',
        payment_application_id: 'pa-1',
        work_package_id: 'wp-1',
        contract_line_id: 'ln-slab',
        claimed_amount: '400.00',
        certified_amount: '400.00',
        approved_amount: '400.00',
      },
    ]);
    packagesMock.mockResolvedValue([
      {
        id: 'wp-1',
        agreement_id: 'ag-1',
        name: 'Footings',
        planned_value: '0',
        completion_percent: '0',
        status: 'in_progress',
        contract_line_id: 'ln-footing',
        created_at: '2026-04-01T00:00:00Z',
        updated_at: '2026-04-01T00:00:00Z',
      },
    ]);
    linesMock.mockResolvedValue([
      sovLine({ id: 'ln-footing', code: '03.10', description: 'Footings' }),
      sovLine({ id: 'ln-slab', code: '03.20', description: 'Slab' }),
    ]);
    remapMock.mockResolvedValue({} as never);
    renderPanel();

    fireEvent.click(await screen.findByText('Lines'));
    const select = (await screen.findByTestId('sub-rollup-line-override')) as HTMLSelectElement;
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(3));
    expect(select.value).toBe('ln-slab');
    expect(within(select).getAllByRole('option')[0]?.textContent).toContain('03.10');

    fireEvent.change(select, { target: { value: '' } });
    await waitFor(() => expect(remapMock).toHaveBeenCalledWith('pal-1', { contract_line_id: null }));
  });

  it('includes exactly the pay applications that were ticked', async () => {
    rollupMock.mockResolvedValue(
      rollup({
        candidates: [
          payApp({ payment_application_id: 'pa-1', application_number: 'PA-1' }),
          payApp({ payment_application_id: 'pa-2', application_number: 'PA-2' }),
        ],
      }),
    );
    includeMock.mockResolvedValue([]);
    renderPanel();

    const include = await screen.findByTestId('sub-rollup-include');
    expect(include).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Include pay application PA-2'));
    fireEvent.click(include);

    await waitFor(() => expect(includeMock).toHaveBeenCalledWith('claim-1', ['pa-2']));
  });

  it('words a refusal by its code rather than passing the server sentence through', async () => {
    rollupMock.mockResolvedValue(rollup({ candidates: [payApp()] }));
    includeMock.mockRejectedValue(
      new ApiError(422, 'Unprocessable', {
        detail: { code: 'currency_mismatch', message: 'server sentence' },
      }),
    );
    renderPanel();

    fireEvent.click(await screen.findByLabelText('Include pay application PA-1'));
    fireEvent.click(screen.getByTestId('sub-rollup-include'));

    await waitFor(() => expect(addToast).toHaveBeenCalled());
    const toast = addToast.mock.calls[0]?.[0] as { type: string; title: string };
    expect(toast.type).toBe('error');
    expect(toast.title).toMatch(/different currency/i);
    expect(toast.title).not.toContain('server sentence');
  });

  it('offers no include, exclude or re-map once the claim is past editing', async () => {
    rollupMock.mockResolvedValue(
      rollup({
        included: [payApp({ progress_claim_id: 'claim-1' })],
        candidates: [payApp({ payment_application_id: 'pa-9', application_number: 'PA-9' })],
        unmapped_lines: [
          {
            payment_application_id: 'pa-1',
            application_number: 'PA-1',
            line_id: 'pal-1',
            work_package_id: 'wp-1',
            work_package_name: 'Cleanup',
            approved_amount: '50.00',
            claimed_amount: '50.00',
            reason: 'none',
            contract_line_id: null,
          },
        ],
      }),
    );
    renderPanel(false);

    await screen.findByTestId('sub-rollup-panel');
    expect(screen.queryByTestId('sub-rollup-include')).toBeNull();
    expect(screen.queryByText('Exclude')).toBeNull();
    expect(screen.queryByTestId('sub-rollup-remap')).toBeNull();
    expect(excludeMock).not.toHaveBeenCalled();
  });

  it('re-maps an unmapped line onto a billable SOV line only', async () => {
    rollupMock.mockResolvedValue(
      rollup({
        included: [payApp({ progress_claim_id: 'claim-1' })],
        unmapped_lines: [
          {
            payment_application_id: 'pa-1',
            application_number: 'PA-1',
            line_id: 'pal-1',
            work_package_id: 'wp-1',
            work_package_name: 'Cleanup',
            approved_amount: '50.00',
            claimed_amount: '50.00',
            reason: 'parent_line',
            contract_line_id: 'ln-group',
          },
        ],
      }),
    );
    linesMock.mockResolvedValue([
      sovLine({ id: 'ln-group', code: '03', description: 'Concrete' }),
      sovLine({ id: 'ln-footing', code: '03.10', description: 'Footings', parent_line_id: 'ln-group' }),
    ]);
    remapMock.mockResolvedValue({} as never);
    renderPanel();

    const select = (await screen.findByTestId('sub-rollup-remap')) as HTMLSelectElement;
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(2));
    const values = within(select)
      .getAllByRole('option')
      .map((o) => (o as HTMLOptionElement).value);
    expect(values).toEqual(['', 'ln-footing']);

    fireEvent.change(select, { target: { value: 'ln-footing' } });
    await waitFor(() =>
      expect(remapMock).toHaveBeenCalledWith('pal-1', { contract_line_id: 'ln-footing' }),
    );
  });

  it('says certificates were not checked when the claim has no period end', async () => {
    rollupMock.mockResolvedValue(
      rollup({ as_of: null, included: [payApp({ certificates_ok: null, progress_claim_id: 'claim-1' })] }),
    );
    renderPanel();
    expect(await screen.findByText(/Certificates not checked/)).toBeInTheDocument();
    expect(screen.queryByText('Certificates valid')).toBeNull();
  });

  it('flags a lapsed certificate and a missing waiver the agreement requires', async () => {
    rollupMock.mockResolvedValue(
      rollup({
        included: [
          payApp({
            progress_claim_id: 'claim-1',
            waiver: {
              state: 'none',
              amount_covered: '0',
              covers_net: false,
              through_date: null,
              through_date_basis: null,
            },
            certificates_ok: false,
            certificate_findings: [
              { document_type: 'insurance', state: 'expired', source: 'certificate', lapsed_on: '2026-04-15' },
            ],
          }),
        ],
      }),
    );
    renderPanel();
    expect(await screen.findByText('Certificate lapsed')).toBeInTheDocument();
    expect(screen.getByText('No waiver')).toBeInTheDocument();
    expect(screen.getByText('insurance')).toBeInTheDocument();
  });

  it('says a payment-date certificate waits for the payment rather than calling it valid or unchecked', async () => {
    rollupMock.mockResolvedValue(
      rollup({
        included: [
          payApp({
            progress_claim_id: 'claim-1',
            certificates_ok: null,
            paid_on: null,
            certificates_pending_payment: true,
            payment_date_findings: [
              {
                document_type: 'construction_tax_exemption',
                state: 'pending',
                judged_on: null,
                lapsed_on: null,
                valid_until: '2026-12-31',
              },
            ],
          }),
        ],
      }),
    );
    renderPanel();
    expect(await screen.findByText('Certificate checked on the payment date')).toBeInTheDocument();
    expect(screen.queryByText('Certificates valid')).toBeNull();
    expect(screen.queryByText(/Certificates not checked/)).toBeNull();
    expect(screen.queryByText('construction_tax_exemption')).toBeNull();
  });

  it('names a payment-date certificate that nothing on file could cover, even before the payment', async () => {
    rollupMock.mockResolvedValue(
      rollup({
        included: [
          payApp({
            progress_claim_id: 'claim-1',
            certificates_ok: null,
            paid_on: null,
            certificates_pending_payment: true,
            payment_date_findings: [
              {
                document_type: 'construction_tax_exemption',
                state: 'pending_invalid',
                judged_on: null,
                lapsed_on: null,
                valid_until: null,
              },
            ],
          }),
        ],
      }),
    );
    renderPanel();
    expect(await screen.findByText('Certificate checked on the payment date')).toBeInTheDocument();
    expect(screen.getByText('construction_tax_exemption')).toBeInTheDocument();
  });

  it('lists a payment-date certificate that did not cover a payment already made', async () => {
    rollupMock.mockResolvedValue(
      rollup({
        included: [
          payApp({
            progress_claim_id: 'claim-1',
            status: 'paid',
            certificates_ok: false,
            paid_on: '2026-05-05',
            certificates_pending_payment: false,
            payment_date_findings: [
              {
                document_type: 'construction_tax_exemption',
                state: 'expired',
                judged_on: '2026-05-05',
                lapsed_on: '2026-04-30',
                valid_until: '2026-04-30',
              },
            ],
          }),
        ],
      }),
    );
    renderPanel();
    expect(await screen.findByText('Certificate lapsed')).toBeInTheDocument();
    expect(screen.getByText('construction_tax_exemption')).toBeInTheDocument();
  });

  it('removes itself when the subcontractors module is not there', async () => {
    rollupMock.mockRejectedValue(new ApiError(404, 'Not Found', { detail: 'Not Found' }));
    const { container } = renderPanel();
    await waitFor(() => expect(rollupMock).toHaveBeenCalled());
    await waitFor(() => expect(container.querySelector('[data-testid="sub-rollup-panel"]')).toBeNull());
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('previews the subs suggestion and commits exactly what it suggested', async () => {
    rollupMock.mockResolvedValue(
      rollup({
        included: [payApp({ progress_claim_id: 'claim-1' })],
        unmapped_lines: [
          {
            payment_application_id: 'pa-1',
            application_number: 'PA-1',
            line_id: 'pal-2',
            work_package_id: 'wp-2',
            work_package_name: 'Cleanup',
            approved_amount: '50.00',
            claimed_amount: '50.00',
            reason: 'none',
            contract_line_id: null,
          },
        ],
      }),
    );
    suggestMock.mockResolvedValue({
      claim_id: 'claim-1',
      contract_id: 'ct-1',
      currency: 'USD',
      items: [
        {
          contract_line_id: 'ln-footing',
          contract_line_code: '03.10',
          contract_line_description: 'Footings',
          boq_position_id: null,
          unit: null,
          contract_quantity: '1',
          contract_line_value: '5000',
          // Percent to date, while the value is this period's alone.
          observed_pct: '40',
          period_label: null,
          recorded_at: null,
          period_completed_qty: '0',
          period_completed_value: '1500',
          cumulative_completed_value: '2000',
          origin: 'subcontract',
          current_period_value: null,
        },
      ],
      skipped_unlinked: 1,
      skipped_no_progress: 0,
      skipped_foreign_currency: 0,
      gross: '1500',
      retention: '0',
      prior_claims_total: '500',
      net_due: '1500',
    });
    commitMock.mockResolvedValue({} as never);
    renderPanel();

    fireEvent.click(await screen.findByTestId('sub-rollup-suggest'));
    await waitFor(() => expect(screen.getByTestId('populate-preview-table')).toBeInTheDocument());
    expect(suggestMock).toHaveBeenCalledWith('claim-1');
    expect(populateMock).not.toHaveBeenCalled();
    // The unmapped count is said in the panel's words, not as a BOQ link.
    expect(screen.getByText(/land on no billable line/)).toBeInTheDocument();
    expect(screen.queryByText(/not linked to a BOQ position/)).toBeNull();

    fireEvent.click(screen.getByText('Commit lines'));
    // Pinned so a change in how the commit reads the percent or the value
    // breaks here instead of billing a different figure.
    await waitFor(() =>
      expect(commitMock).toHaveBeenCalledWith('claim-1', [
        { contract_line_id: 'ln-footing', period_completed_pct: 40, period_completed_value: 1500 },
      ]),
    );
  });

  it('offers the suggestion only while the claim can still change', async () => {
    rollupMock.mockResolvedValue(rollup({ included: [payApp({ progress_claim_id: 'claim-1' })] }));
    renderPanel(false);
    await screen.findByTestId('sub-rollup-panel');
    expect(screen.queryByTestId('sub-rollup-suggest')).toBeNull();
  });

  it('says an included pay application without lines is not billed, rather than showing a zero', async () => {
    rollupMock.mockResolvedValue(
      rollup({ included: [payApp({ line_count: 0, claimed_amount: '0', approved_amount: '0' })] }),
    );
    renderPanel();
    const flag = await screen.findByTestId('sub-rollup-no-lines');
    expect(flag.textContent).toBe('No lines, not billed');
  });
});
