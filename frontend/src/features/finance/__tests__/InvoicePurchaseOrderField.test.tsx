// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The purchase order picker on a supplier invoice.
 *
 * Pins what the server also enforces: only this supplier's orders on this
 * project are offered, never a draft or a cancelled one; the order's value,
 * what is invoiced on it and what is still open are shown net; and the
 * three-way match findings come through as warnings that do not block.
 *
 * Run:  npx vitest run src/features/finance/__tests__/InvoicePurchaseOrderField.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { InvoicePurchaseOrderField } from '../InvoicePurchaseOrderField';

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

const ORDERS = [
  {
    id: 'po-issued',
    po_number: 'PO-0007',
    status: 'issued',
    currency_code: 'EUR',
    amount_subtotal: '50000.00',
    invoiced_net: '40000.00',
    invoice_count: 1,
  },
  { id: 'po-draft', po_number: 'PO-0008', status: 'draft', currency_code: 'EUR', amount_subtotal: '10' },
  { id: 'po-cancelled', po_number: 'PO-0009', status: 'cancelled', currency_code: 'EUR', amount_subtotal: '10' },
];

function renderField(props: Partial<Parameters<typeof InvoicePurchaseOrderField>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InvoicePurchaseOrderField
        projectId="proj-1"
        contactId="vendor-1"
        value=""
        onChange={vi.fn()}
        amountSubtotal={0}
        {...props}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.apiGet.mockReset().mockResolvedValue({ items: ORDERS, total: ORDERS.length });
  api.apiPost.mockReset().mockResolvedValue({ results: [] });
});

describe('InvoicePurchaseOrderField', () => {
  it('asks for the supplier before offering any order', () => {
    renderField({ contactId: '' });
    expect(screen.getByTestId('invoice-po-pick-supplier')).toBeInTheDocument();
    expect(api.apiGet).not.toHaveBeenCalled();
  });

  it("offers only this supplier's orders on this project, never a draft or cancelled one", async () => {
    renderField();
    await screen.findByRole('option', { name: 'PO-0007' });
    const url = String(api.apiGet.mock.calls[0]?.[0]);
    expect(url).toContain('project_id=proj-1');
    expect(url).toContain('vendor_contact_id=vendor-1');
    const options = within(screen.getByTestId('invoice-po-select'))
      .getAllByRole('option')
      .map((o) => o.textContent);
    expect(options).not.toContain('PO-0008');
    expect(options).not.toContain('PO-0009');
  });

  it('shows ordered, invoiced to date and still open for the chosen order', async () => {
    renderField({ value: 'po-issued' });
    const figures = await screen.findByTestId('invoice-po-figures');
    expect(figures.textContent).toMatch(/50[,.\s\u00a0\u202f]?000/);
    expect(figures.textContent).toMatch(/40[,.\s\u00a0\u202f]?000/);
    expect(figures.textContent).toMatch(/10[,.\s\u00a0\u202f]?000/);
    expect(figures.textContent).toContain('Net of VAT');
  });

  it('shows the match findings as warnings that do not block', async () => {
    api.apiPost.mockResolvedValue({
      results: [
        { rule_id: 'procurement.invoice_within_order', severity: 'warning', passed: false, message: 'Exceeds PO-0007' },
        { rule_id: 'procurement.invoice_value_received', severity: 'warning', passed: true, message: 'ok' },
      ],
    });
    renderField({ value: 'po-issued', amountSubtotal: 12000, invoiceId: 'inv-1' });

    const box = await screen.findByTestId('invoice-po-warnings', {}, { timeout: 3000 });
    expect(box.textContent).toContain('Exceeds PO-0007');
    expect(box.textContent).not.toContain('ok');
    expect(box.textContent).toMatch(/can still be saved/);
    await waitFor(() => expect(api.apiPost).toHaveBeenCalled());
    const [path, body] = api.apiPost.mock.calls[0] ?? [];
    expect(path).toBe('/v1/procurement/po-issued/invoice-check/');
    expect(body).toMatchObject({ amount_subtotal: '12000', line_items: [], invoice_id: 'inv-1' });
  });

  it('checks nothing while no order is chosen', async () => {
    renderField({ amountSubtotal: 12000 });
    await screen.findByRole('option', { name: 'PO-0007' });
    expect(api.apiPost).not.toHaveBeenCalled();
  });

  it.each([
    ['9007199254740993.01', '9007199254740993.00', '$9,007,199,254,740,993.01', '$9,007,199,254,740,993.00', '$0.01'],
    ['10.10', '0.10', '$10.10', '$0.10', '$10.00'],
    ['10.00', '10.01', '$10.00', '$10.01', '$0.00'],
    ['-1.00', '0.00', '-$1.00', '$0.00', '$0.00'],
    ['10.00', '-1.00', '$10.00', '-$1.00', '$11.00'],
    ['10.00', undefined, '$10.00', '$0.00', '$10.00'],
  ])('keeps exact order %s and invoiced %s figures without negative open balance', async (
    ordered, invoiced, orderedText, invoicedText, openText,
  ) => {
    api.apiGet.mockResolvedValue({ items: [{ ...ORDERS[0], currency_code: 'USD',
      amount_subtotal: ordered, invoiced_net: invoiced }], total: 1 });
    renderField({ value: 'po-issued' });
    const figures = await screen.findByTestId('invoice-po-figures');
    const values = Array.from(figures.querySelectorAll('dd')).map((node) => node.textContent);
    expect(values).toEqual([orderedText, invoicedText, openText]);
  });

  it.each(['NaN', 'Infinity', 'not-money'])('does not present invalid order %s as a zero balance', async (ordered) => {
    api.apiGet.mockResolvedValue({ items: [{ ...ORDERS[0], currency_code: 'USD',
      amount_subtotal: ordered, invoiced_net: '1.00' }], total: 1 });
    renderField({ value: 'po-issued' });
    const figures = await screen.findByTestId('invoice-po-figures');
    const values = Array.from(figures.querySelectorAll('dd')).map((node) => node.textContent);
    expect(values).toEqual(['—', '$1.00', '—']);
  });

  it('does not fabricate figures when the selected order cannot be loaded', async () => {
    api.apiGet.mockRejectedValue(new Error('Unavailable'));
    renderField({ value: 'po-issued' });
    await screen.findByTestId('invoice-po-no-orders');
    expect(screen.queryByTestId('invoice-po-figures')).not.toBeInTheDocument();
  });

  it.each(['Infinity', 'NaN'])('does not present invalid invoiced %s as a known balance', async (invoiced) => {
    api.apiGet.mockResolvedValue({ items: [{ ...ORDERS[0], currency_code: 'USD',
      amount_subtotal: '10.00', invoiced_net: invoiced }], total: 1 });
    renderField({ value: 'po-issued' });
    const figures = await screen.findByTestId('invoice-po-figures');
    const values = Array.from(figures.querySelectorAll('dd')).map((node) => node.textContent);
    expect(values).toEqual(['$10.00', '—', '—']);
  });
});
