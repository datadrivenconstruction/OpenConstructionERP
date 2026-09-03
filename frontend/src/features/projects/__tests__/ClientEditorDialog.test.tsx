// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ClientEditorDialog: add two addresses, star the second, move it up, then
 * save - the ONE PATCH must carry both rows in the new order with the
 * starred one primary and mirrored into `address`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/features/contacts/api', () => ({
  createContact: vi.fn(),
  updateContact: vi.fn(async (id: string, body?: Record<string, unknown>) => ({
    id,
    contact_type: 'client',
    company_name: body?.company_name ?? 'Acme Holdings',
    ...(body ?? {}),
  })),
}));

import { updateContact } from '@/features/contacts/api';
import type { Contact } from '@/features/contacts/api';
import { ClientEditorDialog } from '../ClientEditorDialog';

const contact = {
  id: '11111111-2222-4333-8444-555555555555',
  contact_type: 'client',
  company_name: 'Acme Holdings',
  first_name: null,
  last_name: null,
  legal_name: null,
  vat_number: null,
  primary_email: null,
  primary_phone: null,
  website: null,
  country_code: null,
  address: null,
  prequalification_status: null,
  payment_terms_days: null,
  notes: null,
  custom_properties: { brand_color: '#2563eb', other_module: { keep: 1 } },
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as Contact;

function renderDialog(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ClientEditorDialog contact={contact} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe('ClientEditorDialog', () => {
  beforeEach(() => vi.mocked(updateContact).mockClear());

  it('adds, stars, reorders and saves addresses in one PATCH', async () => {
    renderDialog();
    expect(screen.getByTestId('client-editor')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('client-editor-add-address'));
    fireEvent.click(screen.getByTestId('client-editor-add-address'));
    const rows = screen.getAllByTestId('client-editor-address');
    expect(rows).toHaveLength(2);
    // First row is primary by construction.
    expect(rows[0]).toHaveAttribute('data-primary', 'true');

    fireEvent.change(within(rows[0]!).getByTestId('client-editor-address-line1'), { target: { value: '12 Example Street' } });
    fireEvent.change(within(rows[0]!).getByTestId('client-editor-address-label'), { target: { value: 'Head office' } });
    fireEvent.change(within(rows[1]!).getByTestId('client-editor-address-line1'), { target: { value: '4 Sample Road' } });
    fireEvent.change(within(rows[1]!).getByTestId('client-editor-address-suburb'), { target: { value: 'Sampletown' } });
    fireEvent.change(within(rows[1]!).getByTestId('client-editor-address-postcode'), { target: { value: '2000' } });

    // Star the second, then move it up.
    fireEvent.click(within(rows[1]!).getByTestId('client-editor-address-primary'));
    fireEvent.click(within(screen.getAllByTestId('client-editor-address')[1]!).getByTestId('client-editor-address-up'));
    const reordered = screen.getAllByTestId('client-editor-address');
    expect(within(reordered[0]!).getByTestId('client-editor-address-line1')).toHaveValue('4 Sample Road');
    expect(reordered[0]).toHaveAttribute('data-primary', 'true');
    expect(reordered[1]).not.toHaveAttribute('data-primary');

    fireEvent.click(screen.getByTestId('client-editor-save'));
    await waitFor(() => expect(updateContact).toHaveBeenCalledTimes(1));
    const [id, body] = vi.mocked(updateContact).mock.calls[0]!;
    expect(id).toBe(contact.id);
    expect(body.custom_properties).toMatchObject({ brand_color: '#2563eb', other_module: { keep: 1 } });
    const stored = body.custom_properties!.addresses as Array<{ line1: string; is_primary: boolean }>;
    expect(stored.map((a) => [a.line1, a.is_primary])).toEqual([
      ['4 Sample Road', true],
      ['12 Example Street', false],
    ]);
    expect(body.address).toMatchObject({ text: '4 Sample Road', city: 'Sampletown', postcode: '2000' });
  });

  it('blocks save while an address has no line 1 and shows the error', async () => {
    renderDialog();
    fireEvent.click(screen.getByTestId('client-editor-add-address'));
    fireEvent.click(screen.getByTestId('client-editor-save'));
    expect(await screen.findByText(/line 1 is required/i)).toBeInTheDocument();
    expect(updateContact).not.toHaveBeenCalled();
  });

  it('Escape closes, Enter in the last field saves', async () => {
    const { onClose } = renderDialog();
    fireEvent.keyDown(screen.getByTestId('client-editor-name'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    // With no addresses the phone field is the last one.
    fireEvent.keyDown(screen.getByTestId('client-editor-phone'), { key: 'Enter' });
    await waitFor(() => expect(updateContact).toHaveBeenCalledTimes(1));
  });

  it('closes on a backdrop click and on Escape pressed outside the panel', () => {
    const { onClose } = renderDialog();
    fireEvent.mouseDown(screen.getByTestId('client-editor-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(1);
    // Focus still on the button that opened it (the page behind).
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('focuses the name on open and hands focus back to the opener on close', async () => {
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    opener.focus();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <ClientEditorDialog contact={contact} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('client-editor-name')));
    rerender(
      <QueryClientProvider client={qc}>
        <ClientEditorDialog contact={null} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it('trims address fields before they are stored and mirrored', async () => {
    renderDialog();
    fireEvent.click(screen.getByTestId('client-editor-add-address'));
    const row = screen.getByTestId('client-editor-address');
    fireEvent.change(within(row).getByTestId('client-editor-address-line1'), { target: { value: '  9 Ninth Street  ' } });
    fireEvent.change(within(row).getByTestId('client-editor-address-suburb'), { target: { value: ' Sampletown ' } });
    fireEvent.click(screen.getByTestId('client-editor-save'));
    await waitFor(() => expect(updateContact).toHaveBeenCalledTimes(1));
    const [, body] = vi.mocked(updateContact).mock.calls[0]!;
    const stored = body.custom_properties!.addresses as Array<{ line1: string; suburb: string }>;
    expect(stored[0]).toMatchObject({ line1: '9 Ninth Street', suburb: 'Sampletown' });
    expect(body.address).toMatchObject({ line1: '9 Ninth Street', text: '9 Ninth Street', city: 'Sampletown' });
  });
});
