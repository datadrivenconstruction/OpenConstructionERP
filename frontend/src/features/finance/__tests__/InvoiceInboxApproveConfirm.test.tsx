// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Approving a captured invoice asks first, naming the amount and currency, and the
 * order-mismatch acknowledgement still gates the button and travels with the call.
 *
 * Run:  npx vitest run src/features/finance/__tests__/InvoiceInboxApproveConfirm.test.tsx --maxWorkers=1
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn() }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      let s = String(opts?.defaultValue ?? key);
      for (const [k, v] of Object.entries(opts ?? {})) s = s.replace(`{{${k}}}`, String(v));
      return s;
    },
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));
vi.mock('@/shared/lib/api', () => ({
  apiGet: api.apiGet,
  apiPost: api.apiPost,
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  API_BASE: '/api',
  getAuthToken: () => '',
  extractErrorMessageFromBody: () => null,
  downloadWithAuth: vi.fn(),
}));
vi.mock('../InvoiceInboxOrderLink', () => ({
  InvoiceInboxOrderLink: () => null,
  hasOrderMismatch: (v?: Array<{ code: string }>) => (v ?? []).some((f) => f.code.startsWith('po_match:')),
}));

import { InvoiceInboxTab } from '../InvoiceInboxTab';

function capture(validation: Array<Record<string, unknown>> = []) {
  return {
    id: 'c1',
    project_id: 'p1',
    status: 'coded',
    doc_kind: 'invoice',
    original_filename: 'a.pdf',
    has_document: false,
    supplier_name: 'Acme Steel',
    supplier_tax_id: null,
    supplier_contact_id: null,
    po_reference: null,
    purchase_order_id: null,
    invoice_number: 'INV-77',
    invoice_date: '2026-10-01',
    due_date: null,
    currency_code: 'CHF',
    amount_net: '1000.00',
    amount_tax: '81.00',
    amount_gross: '1081.00',
    line_items: [],
    extraction_engine: 'manual',
    field_confidence: {},
    booking_expense_account: '4000',
    booking_tax_account: null,
    booking_payable_account: '2000',
    booking_cost_code: null,
    approver_id: null,
    approved_at: null,
    rejected_reason: null,
    queried_note: null,
    posted_at: null,
    posted_transaction_ref: null,
    archive_hash: null,
    retention_until: null,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    validation,
    booking_proposal: null,
  };
}

function mount(validation: Array<Record<string, unknown>> = []) {
  const row = capture(validation);
  api.apiGet.mockImplementation(async (url: string) => {
    if (url.includes('/audit')) return { items: [], total: 0 };
    if (url.includes('/gaap/accounts')) return { items: [], total: 0 };
    if (url.includes('/finance/inbox/c1')) return row;
    return { items: [row], total: 1 };
  });
  api.apiPost.mockResolvedValue(row);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InvoiceInboxTab projectId="p1" />
    </QueryClientProvider>,
  );
}

async function openReview() {
  fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
  return screen.findByTestId('inbox-approve');
}

describe('invoice inbox approve', () => {
  beforeEach(() => {
    api.apiGet.mockReset();
    api.apiPost.mockReset();
  });

  it('asks first, naming amount and currency, and approves only on confirm', async () => {
    mount();
    fireEvent.click(await openReview());
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog.textContent).toMatch(/1\D?081\D00/);
    expect(dialog.textContent).toContain('CHF');
    expect(api.apiPost).not.toHaveBeenCalled();

    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve' }));
    await waitFor(() =>
      expect(api.apiPost).toHaveBeenCalledWith('/v1/finance/inbox/c1/approve', { acknowledge_match: false }),
    );
  });

  it('does not approve when the dialog is cancelled', async () => {
    mount();
    fireEvent.click(await openReview());
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }));
    expect(api.apiPost).not.toHaveBeenCalled();
  });

  it('keeps the mismatch acknowledgement in front of the dialog and sends it', async () => {
    mount([
      { severity: 'warning', code: 'po_match:procurement.invoice_within_order', message: 'Over order', field: null },
    ]);
    const approve = (await openReview()) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    fireEvent.click(await screen.findByRole('checkbox'));
    expect(approve.disabled).toBe(false);
    fireEvent.click(approve);
    await screen.findByRole('alertdialog');
    fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve' }));
    await waitFor(() =>
      expect(api.apiPost).toHaveBeenCalledWith('/v1/finance/inbox/c1/approve', { acknowledge_match: true }),
    );
  });
});
