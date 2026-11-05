import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AcceptDialog, CustomerEmpty, PlaceholderChips, SendAction } from './offerParts';
import { insertAt, type Offer } from './api';
import { patternHasSequence } from './OfferSettingsPanel';

const created = vi.fn();
vi.mock('./api', async (orig) => {
  const mod = await orig<typeof import('./api')>();
  return { ...mod, createCustomer: (...a: unknown[]) => created(...a) };
});

describe('SendAction', () => {
  it('is disabled and names the first error while the offer cannot be sent', () => {
    const onSend = vi.fn();
    render(<SendAction canSend={false} firstError="No customer is set." pending={false} onSend={onSend} />);
    const button = screen.getByRole('button') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByTestId('send-blocked-reason').textContent).toBe('No customer is set.');
    fireEvent.click(button);
    expect(onSend).not.toHaveBeenCalled();
  });

  it('sends when nothing blocks it and shows no reason', () => {
    const onSend = vi.fn();
    render(<SendAction canSend firstError={null} pending={false} onSend={onSend} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('send-blocked-reason')).toBeNull();
  });
});

describe('PlaceholderChips', () => {
  it('hands the clicked placeholder to the editor', () => {
    const onInsert = vi.fn();
    render(<PlaceholderChips onInsert={onInsert} />);
    fireEvent.click(screen.getByText('{valid_until}'));
    expect(onInsert).toHaveBeenCalledWith('{valid_until}');
  });

  it('inserts at the caret and replaces a selection', () => {
    expect(insertAt('Valid until .', 12, 12, '{valid_until}')).toEqual({ text: 'Valid until {valid_until}.', caret: 25 });
    expect(insertAt('abcdef', 1, 4, 'X').text).toBe('aXef');
  });
});

describe('CustomerEmpty', () => {
  beforeEach(() => created.mockReset());

  it('creates the customer in place and picks it at once', async () => {
    created.mockResolvedValue({ id: 'c-1' });
    const onCreated = vi.fn();
    render(<CustomerEmpty projectId="p-1" country="DE" onCreated={onCreated} />);
    fireEvent.click(screen.getByText('Add customer'));
    fireEvent.change(screen.getByLabelText('Customer name'), { target: { value: 'Muster GmbH' } });
    fireEvent.click(screen.getByText('Add customer'));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('c-1'));
    expect(created).toHaveBeenCalledWith(expect.objectContaining({ name: 'Muster GmbH', projectId: 'p-1', setAsProjectClient: true }));
  });

  it('does not submit without a name', () => {
    render(<CustomerEmpty projectId="p-1" country="DE" onCreated={vi.fn()} />);
    fireEvent.click(screen.getByText('Add customer'));
    expect((screen.getByRole('button', { name: 'Add customer' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('AcceptDialog', () => {
  const offer = { totals: { not_included: [{ ordinal: '2.1', description: 'Terrace', total: '3000.00' }] } } as unknown as Offer;

  it('accepts without a contract and explains why when the permission is missing', () => {
    const onConfirm = vi.fn();
    render(<AcceptDialog offer={offer} canCreateContract={false} pending={false} onConfirm={onConfirm} onCancel={vi.fn()} />);
    expect(screen.getByTestId('contract-blocked-reason')).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox', { name: /2\.1/ }));
    fireEvent.click(screen.getAllByText('Mark accepted').pop() as HTMLElement);
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ optional_ordinals: ['2.1'], create_contract: false }));
  });

  it('creates the contract by default when allowed', () => {
    const onConfirm = vi.fn();
    render(<AcceptDialog offer={offer} canCreateContract pending={false} onConfirm={onConfirm} onCancel={vi.fn()} />);
    fireEvent.click(screen.getAllByText('Mark accepted').pop() as HTMLElement);
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ create_contract: true }));
  });
});

describe('numbering pattern', () => {
  it('needs a sequence part', () => {
    expect(patternHasSequence('ANG-{year}-{seq:4}')).toBe(true);
    expect(patternHasSequence('ANG-{year}')).toBe(false);
  });
});
