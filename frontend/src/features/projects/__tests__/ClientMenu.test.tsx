// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ClientMenu + the picker's selected pill: right-click opens the portalled
 * menu with the three pill items, Enter activates the highlighted one,
 * Escape / outside click close it.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ClientMenu, useClientMenu, anchorFromElement } from '../ClientMenu';
import { ClientPicker } from '../ClientPicker';
import type { Contact } from '@/features/contacts/api';

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
  custom_properties: {
    addresses: [{ id: 'a', label: 'Head office', line1: '12 Example Street', suburb: 'Sampletown', state: 'NSW', postcode: '2000', country: '', line2: '', is_primary: true }],
  },
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as Contact;

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(async () => ({ items: [contact], total: 1 })),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

function Harness({ onPick }: { onPick: (k: string) => void }) {
  const menu = useClientMenu();
  return (
    <>
      <button type="button" data-testid="target" onContextMenu={menu.openAt}>
        target
      </button>
      <ClientMenu
        anchor={menu.anchor}
        items={[
          { key: 'one', label: 'One', onSelect: () => onPick('one') },
          { key: 'two', label: 'Two', onSelect: () => onPick('two'), disabled: true },
          { key: 'three', label: 'Three', onSelect: () => onPick('three') },
        ]}
        onClose={menu.close}
        title="Acme Holdings"
      />
    </>
  );
}

describe('ClientMenu', () => {
  it('opens on right-click, walks with arrows, Enter activates, Escape closes', () => {
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    expect(screen.queryByRole('menu')).toBeNull();
    fireEvent.contextMenu(screen.getByTestId('target'), { clientX: 40, clientY: 50 });
    const menu = screen.getByRole('menu');
    expect(menu).toHaveAttribute('aria-label', 'Acme Holdings');
    expect(screen.getByTestId('client-menu-two')).toBeDisabled();
    // Down skips the disabled item.
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    fireEvent.keyDown(menu, { key: 'Enter' });
    expect(onPick).toHaveBeenCalledWith('three');
    expect(screen.queryByRole('menu')).toBeNull();

    fireEvent.contextMenu(screen.getByTestId('target'), { clientX: 40, clientY: 50 });
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();

    fireEvent.contextMenu(screen.getByTestId('target'), { clientX: 40, clientY: 50 });
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('anchors under an element when the event has no coordinates', () => {
    expect(anchorFromElement(null)).toEqual({ x: 8, y: 8 });
  });

  it('takes focus while open and hands it back to the trigger on close', () => {
    render(<Harness onPick={vi.fn()} />);
    const target = screen.getByTestId('target');
    target.focus();
    fireEvent.contextMenu(target, { clientX: 40, clientY: 50 });
    expect(document.activeElement).toBe(screen.getByRole('menu'));
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(target);
  });
});

describe('ClientPicker add-as-new colour strip', () => {
  it('keeps a picked colour when the list is closed and reopened for the same text', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ClientPicker value="" onChange={vi.fn()} />
      </QueryClientProvider>,
    );
    const input = screen.getByTestId('client-picker-input');
    fireEvent.change(input, { target: { value: 'Example New Client' } });
    await screen.findByTestId('client-picker-add');
    fireEvent.click(screen.getByTestId('client-picker-add'));
    fireEvent.click(screen.getByTestId('client-picker-add-swatch'));
    fireEvent.click(screen.getByTestId('client-color-pick-2563eb'));
    expect(screen.getByTestId('client-picker-add-swatch')).toHaveAttribute('data-color', '#2563eb');
    // Escape closes the list; ArrowDown reopens it - the strip is still there.
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(screen.queryByTestId('client-picker-add-color')).toBeNull();
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(screen.getByTestId('client-picker-add-swatch')).toHaveAttribute('data-color', '#2563eb');
    // Typing something else abandons it.
    fireEvent.change(input, { target: { value: 'Example New Client 2' } });
    expect(screen.queryByTestId('client-picker-add-color')).toBeNull();
  });
});

describe('ClientPicker selected pill', () => {
  it('shows the primary address, and right-click offers edit / colour / clear', async () => {
    const onChange = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ClientPicker value={contact.id} onChange={onChange} />
      </QueryClientProvider>,
    );
    const pill = await screen.findByTestId('client-picker-selected');
    expect(await screen.findByText('Acme Holdings')).toBeInTheDocument();
    expect(screen.getByText('12 Example Street, Sampletown NSW 2000')).toBeInTheDocument();

    fireEvent.contextMenu(pill, { clientX: 10, clientY: 10 });
    expect(screen.getByTestId('client-menu-edit')).toBeEnabled();
    expect(screen.getByTestId('client-menu-colour')).toBeEnabled();
    fireEvent.click(screen.getByTestId('client-menu-clear'));
    expect(onChange).toHaveBeenCalledWith('');

    // The pencil opens the editor directly.
    fireEvent.click(screen.getByTestId('client-picker-edit'));
    expect(screen.getByTestId('client-editor')).toBeInTheDocument();
    expect(screen.getByTestId('client-editor-name')).toHaveValue('Acme Holdings');
    expect(screen.getAllByTestId('client-editor-address')).toHaveLength(1);
  });
});
