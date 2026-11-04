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

const SELECTED = { id: 'po-a', po_number: 'PO-0007', status: 'issued', vendor_contact_id: 'c1' };

/** Answer the list endpoint by its search term, and the single-order endpoint by id. */
function serve() {
  api.apiGet.mockImplementation(async (url: string) => {
    if (/\/v1\/procurement\/po-/.test(url)) return SELECTED;
    const q = decodeURIComponent(new URL(url, 'http://x').searchParams.get('search') ?? '').toLowerCase();
    const items = ORDERS.filter((o) => o.po_number.toLowerCase().includes(q));
    return { items, total: items.length };
  });
}

const open = () => fireEvent.focus(screen.getByTestId('inbox-po-select'));

describe('InvoiceInboxOrderLink', () => {
  beforeEach(() => {
    api.apiGet.mockReset();
    serve();
  });

  it('offers only open orders of the known supplier', async () => {
    mount();
    open();
    await waitFor(() => expect(screen.getByRole('button', { name: 'PO-0007' })).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'PO-0008' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'PO-0009' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'PO-0010' })).toBeNull();
  });

  it('offers every open order when the supplier is not known yet', async () => {
    mount({ supplierContactId: null });
    open();
    await waitFor(() => expect(screen.getByRole('button', { name: 'PO-0008' })).toBeTruthy());
    expect(screen.getByRole('button', { name: 'PO-0007' })).toBeTruthy();
  });

  it('searches on the server after a pause, so an order beyond the first page is reachable', async () => {
    mount({ supplierContactId: null });
    open();
    await waitFor(() => expect(api.apiGet).toHaveBeenCalledTimes(1));
    const input = screen.getByTestId('inbox-po-select');
    fireEvent.change(input, { target: { value: 'P' } });
    fireEvent.change(input, { target: { value: 'PO-0008' } });
    await waitFor(() => expect(api.apiGet.mock.calls.some((c) => String(c[0]).includes('search=PO-0008'))).toBe(true));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'PO-0007' })).toBeNull());
    expect(screen.getByRole('button', { name: 'PO-0008' })).toBeTruthy();
    const urls = api.apiGet.mock.calls.map((c) => String(c[0]));
    expect(urls.filter((u) => u.includes('search=PO-0008')).length).toBe(1);
    expect(urls.some((u) => u.includes('search=P&') || u.endsWith('search=P'))).toBe(false);
    expect(urls.every((u) => u.includes('project_id=p1'))).toBe(true);
  });

  it('reports the chosen order', async () => {
    const onChange = mount();
    open();
    fireEvent.click(await screen.findByRole('button', { name: 'PO-0007' }));
    expect(onChange).toHaveBeenCalledWith('po-a');
  });

  it('shows the linked order and reports an empty choice to unlink', async () => {
    const onChange = mount({ value: 'po-a' });
    await waitFor(() => expect((screen.getByTestId('inbox-po-select') as HTMLInputElement).value).toBe('PO-0007'));
    fireEvent.click(screen.getByTestId('inbox-po-clear'));
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('is read-only once the invoice is approved', async () => {
    mount({ disabled: true, value: 'po-a' });
    await waitFor(() => expect((screen.getByTestId('inbox-po-select') as HTMLInputElement).value).toBe('PO-0007'));
    expect((screen.getByTestId('inbox-po-select') as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByTestId('inbox-po-clear')).toBeNull();
  });

  it('says so when nothing matches', async () => {
    api.apiGet.mockResolvedValue({ items: [], total: 0 });
    mount();
    open();
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
