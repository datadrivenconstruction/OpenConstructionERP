// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The commitment panel on a supplier invoice and the approval gate on a list row.
 *
 * Worked example: an order for 10,000.00 with 1,500.00 of approved changes and
 * 9,000.00 already invoiced leaves 2,500.00 open. An invoice of 2,600.00 would
 * be refused on approval, so the panel says why and the Approve button is
 * disabled with the same reason. A warning alone never disables anything.
 *
 * Run:  npx vitest run src/features/finance/__tests__/InvoiceCommitmentCheck.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import {
  InvoiceApprovalGate,
  InvoiceCommitmentCheck,
  InvoiceSubcontractField,
  blockingReason,
  type PostingCheck,
} from '../InvoiceCommitmentCheck';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
    i18n: { language: 'en' },
  }),
}));

vi.mock('@/shared/lib/api', () => ({
  apiGet: api.apiGet,
  apiPost: api.apiPost,
}));

const COMMITMENT = {
  kind: 'purchase_order' as const,
  id: 'po-1',
  ref: 'PO-0007',
  status: 'issued',
  currency_code: 'USD',
  original: '10000.00',
  approved_changes: '1500.00',
  revised: '11500.00',
  invoiced: '9000.00',
  remaining: '2500.00',
  paid: '0',
  retention_percent: '0',
  invoices_in_other_currency: 0,
  shared_change_orders: 0,
};

const OVER = 'Invoice S-1001 is 100.00 over the open commitment on PO-0007';

function check(results: PostingCheck['report']['results'], commitment = COMMITMENT): PostingCheck {
  return {
    commitment,
    blocking: results.some((r) => !r.passed && r.severity === 'error'),
    report: { results },
  };
}

const REFUSED = check([
  {
    rule_id: 'invoice_posting.within_commitment',
    severity: 'error',
    passed: false,
    message: OVER,
    suggestion: 'Approve a change order for the difference or reduce the invoice',
  },
]);

const WARNED = check([
  { rule_id: 'invoice_posting.within_commitment', severity: 'error', passed: true, message: 'ok' },
  {
    rule_id: 'invoice_posting.possible_duplicate',
    severity: 'warning',
    passed: false,
    message: 'Same supplier, amount and date as S-0999',
  },
]);

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

const INPUT = { project_id: 'proj-1', amount_subtotal: '2600.00', purchase_order_id: 'po-1', currency_code: 'USD' };

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiPost.mockReset();
});

describe('InvoiceCommitmentCheck', () => {
  it('shows the original, approved changes, invoiced and remaining commitment', async () => {
    api.apiPost.mockResolvedValue(WARNED);
    wrap(<InvoiceCommitmentCheck input={INPUT} />);
    expect(await screen.findByTestId('invoice-commitment-figures')).toBeInTheDocument();
    expect(screen.getByTestId('commitment-original').textContent).toContain('10,000.00');
    expect(screen.getByTestId('commitment-changes').textContent).toContain('1,500.00');
    expect(screen.getByTestId('commitment-invoiced').textContent).toContain('9,000.00');
    expect(screen.getByTestId('commitment-remaining').textContent).toContain('2,500.00');
    expect(api.apiPost).toHaveBeenCalledWith('/v1/finance/invoices/posting-check/', INPUT);
  });

  it('shows the certificate summary A, B, A - B, C and the current payment due', async () => {
    // 9,000 billed before with 450 held at 5 %; this invoice bills 2,500.
    api.apiPost.mockResolvedValue({
      ...WARNED,
      summary: {
        completed_to_date: '11500.00',
        retention: '575.00',
        earned_less_retention: '10925.00',
        previously_certified: '8550.00',
        current_due: '2375.00',
        balance_to_finish: '0.00',
      },
    });
    wrap(<InvoiceCommitmentCheck input={INPUT} />);
    expect((await screen.findByTestId('pay-summary-completed_to_date')).textContent).toContain('11,500.00');
    expect(screen.getByTestId('pay-summary-retention').textContent).toContain('575.00');
    expect(screen.getByTestId('pay-summary-previously_certified').textContent).toContain('8,550.00');
    expect(screen.getByTestId('pay-summary-current_due').textContent).toContain('2,375.00');
    expect(screen.getByTestId('invoice-pay-summary').textContent).toContain('Current payment due (A - B - C)');
  });

  it('says approval will be refused and hands the reason to the form', async () => {
    api.apiPost.mockResolvedValue(REFUSED);
    const onBlockingChange = vi.fn();
    wrap(<InvoiceCommitmentCheck input={INPUT} onBlockingChange={onBlockingChange} />);
    const errors = await screen.findByTestId('invoice-commitment-errors');
    expect(errors.textContent).toContain(OVER);
    expect(errors.textContent).toContain('Approve a change order');
    await waitFor(() => expect(onBlockingChange).toHaveBeenLastCalledWith(OVER));
  });

  it('a warning alone is shown but blocks nothing', async () => {
    api.apiPost.mockResolvedValue(WARNED);
    const onBlockingChange = vi.fn();
    wrap(<InvoiceCommitmentCheck input={INPUT} onBlockingChange={onBlockingChange} />);
    expect((await screen.findByTestId('invoice-commitment-warnings')).textContent).toContain('S-0999');
    expect(screen.queryByTestId('invoice-commitment-errors')).toBeNull();
    expect(blockingReason(WARNED)).toBeNull();
  });

  it('renders nothing for an invoice that bills no commitment and fails no rule', async () => {
    api.apiPost.mockResolvedValue({ commitment: null, blocking: false, report: { results: [] } });
    const { container } = wrap(<InvoiceCommitmentCheck input={{ project_id: 'proj-1', amount_subtotal: '5' }} />);
    await waitFor(() => expect(api.apiPost).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="invoice-commitment-check"]')).toBeNull();
  });
});

describe('InvoiceApprovalGate', () => {
  const row = {
    id: 'inv-1',
    project_id: 'proj-1',
    status: 'pending',
    contact_id: 'vendor-1',
    amount_subtotal: '2600.00',
    currency_code: 'USD',
    purchase_order_id: 'po-1',
  };

  function Approve({ reason }: { reason: string | null }) {
    return (
      <button type="button" disabled={!!reason} title={reason ?? undefined}>
        Approve
      </button>
    );
  }

  it('disables Approve with the reason when approval would be refused', async () => {
    api.apiPost.mockResolvedValue(REFUSED);
    wrap(<InvoiceApprovalGate invoice={row}>{(reason) => <Approve reason={reason} />}</InvoiceApprovalGate>);
    const button = screen.getByRole('button', { name: 'Approve' });
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAttribute('title', OVER);
  });

  it('leaves Approve enabled and asks nothing for an invoice that is not pending', async () => {
    wrap(
      <InvoiceApprovalGate invoice={{ ...row, status: 'draft' }}>
        {(reason) => <Approve reason={reason} />}
      </InvoiceApprovalGate>,
    );
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
    expect(api.apiPost).not.toHaveBeenCalled();
  });
});

describe('InvoiceSubcontractField', () => {
  it('offers only this supplier subcontract agreements and hides itself when there are none', async () => {
    api.apiGet.mockResolvedValue([COMMITMENT, { ...COMMITMENT, kind: 'subcontract', id: 'sa-1', ref: 'Concrete package' }]);
    wrap(<InvoiceSubcontractField projectId="proj-1" contactId="vendor-1" value="" onChange={vi.fn()} />);
    const select = await screen.findByTestId('invoice-subcontract-select');
    expect(select.textContent).toContain('Concrete package');
    expect(select.textContent).not.toContain('PO-0007');
    expect(api.apiGet).toHaveBeenCalledWith('/v1/finance/commitments/?project_id=proj-1&contact_id=vendor-1');
  });

  it('is absent where the market has no subcontract agreements', async () => {
    api.apiGet.mockResolvedValue([]);
    const { container } = wrap(
      <InvoiceSubcontractField projectId="proj-1" contactId="vendor-1" value="" onChange={vi.fn()} />,
    );
    await waitFor(() => expect(api.apiGet).toHaveBeenCalled());
    expect(container.querySelector('select')).toBeNull();
  });
});
