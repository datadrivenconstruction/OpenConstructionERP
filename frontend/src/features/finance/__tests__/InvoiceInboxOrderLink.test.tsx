// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The order picker on a captured invoice: offers open orders of the project (the
 * supplier's, when known), never a draft or cancelled one, and reports the choice.
 * The mismatch helper decides whether approval waits for an acknowledgement.
 *
 * Run:  npx vitest run src/features/finance/__tests__/InvoiceInboxOrderLink.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { InvoiceInboxOrderLink, hasOrderMismatch } from '../InvoiceInboxOrderLink';

const api = vi.hoisted(() => ({ apiGet: vi.fn() }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
    i18n: { language: 'en' },
  }),
}));
vi.mock('@/shared/lib/api', () => ({ apiGet: api.apiGet }));

const ORDERS = [
  { id: 'po-a', po_number: 'PO-0007', status: 'issued', vendor_contact_id: 'c1' },
  { id: 'po-b', po_number: 'PO-0008', status: 'issued', vendor_contact_id: 'c2' },
  { id: 'po-c', po_number: 'PO-0009', status: 'draft', vendor_contact_id: 'c1' },
  { id: 'po-d', po_number: 'PO-0010', status: 'cancelled', vendor_contact_id: 'c1' },
];

function mount(props: Partial<React.ComponentProps<typeof InvoiceInboxOrderLink>> = {}) {
  const onChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InvoiceInboxOrderLink
        projectId="p1"
        supplierContactId="c1"
        value=""
        disabled={false}
        onChange={onChange}
        {...props}
      />
    </QueryClientProvider>,
  );
  return onChange;
}

describe('InvoiceInboxOrderLink', () => {
  beforeEach(() => {
    api.apiGet.mockReset();
    api.apiGet.mockResolvedValue({ items: ORDERS, total: ORDERS.length });
  });

  it('offers only open orders of the known supplier', async () => {
    mount();
    await waitFor(() => expect(screen.getByRole('option', { name: 'PO-0007' })).toBeTruthy());
    expect(screen.queryByRole('option', { name: 'PO-0008' })).toBeNull();
    expect(screen.queryByRole('option', { name: 'PO-0009' })).toBeNull();
    expect(screen.queryByRole('option', { name: 'PO-0010' })).toBeNull();
  });

  it('offers every open order when the supplier is not known yet', async () => {
    mount({ supplierContactId: null });
    await waitFor(() => expect(screen.getByRole('option', { name: 'PO-0008' })).toBeTruthy());
    expect(screen.getByRole('option', { name: 'PO-0007' })).toBeTruthy();
  });

  it('reports the chosen order, and an empty choice to unlink', async () => {
    const onChange = mount({ value: 'po-a' });
    await waitFor(() => expect(screen.getByRole('option', { name: 'PO-0007' })).toBeTruthy());
    fireEvent.change(screen.getByTestId('inbox-po-select'), { target: { value: '' } });
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('is read-only once the invoice is approved', async () => {
    mount({ disabled: true });
    await waitFor(() => expect(screen.getByRole('option', { name: 'PO-0007' })).toBeTruthy());
    expect((screen.getByTestId('inbox-po-select') as HTMLSelectElement).disabled).toBe(true);
  });

  it('says so when the project has no open order', async () => {
    api.apiGet.mockResolvedValue({ items: [], total: 0 });
    mount();
    await waitFor(() => expect(screen.getByTestId('inbox-po-no-orders')).toBeTruthy());
  });
});

describe('hasOrderMismatch', () => {
  it('is true only for order-match findings', () => {
    expect(hasOrderMismatch([{ code: 'po_match:procurement.invoice_within_order' }])).toBe(true);
    expect(hasOrderMismatch([{ code: 'po_not_open' }, { code: 'duplicate_invoice' }])).toBe(false);
    expect(hasOrderMismatch(undefined)).toBe(false);
  });
});
