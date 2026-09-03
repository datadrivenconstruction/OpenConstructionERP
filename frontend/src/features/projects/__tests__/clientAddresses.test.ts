// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The client addresses contract (custom_properties.addresses) and the pure
 * list operations the ClientEditorDialog drives: add / update / remove /
 * set primary / reorder, plus the one-PATCH save that mirrors the primary
 * into the contact's plain `address` column.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/features/contacts/api', () => ({
  createContact: vi.fn(),
  updateContact: vi.fn(async (_id: string, body: unknown) => ({ id: _id, ...(body as object) })),
}));

import { updateContact } from '@/features/contacts/api';
import {
  addAddress,
  clientAddresses,
  ensureOnePrimary,
  formatAddress,
  mirrorAddress,
  moveAddress,
  primaryAddress,
  removeAddress,
  saveClientDetails,
  setPrimaryAddress,
  updateAddress,
  validateAddress,
  type ClientAddress,
} from '../clients';

const A: ClientAddress = {
  id: 'a',
  label: 'Head office',
  line1: '12 Example Street',
  line2: 'Level 3',
  suburb: 'Sampletown',
  state: 'NSW',
  postcode: '2000',
  country: 'Australia',
  is_primary: true,
};
const B: ClientAddress = { ...A, id: 'b', label: 'Site', line1: '4 Sample Road', line2: '', is_primary: false };
const C: ClientAddress = { ...A, id: 'c', label: 'Postal', line1: 'PO Box 99', line2: '', is_primary: false };

describe('clientAddresses / primaryAddress', () => {
  it('reads the list off custom_properties and tolerates junk entries', () => {
    const rows = clientAddresses({
      custom_properties: { addresses: [A, 'junk', null, { line1: 'No id', city: 'Legacy', postal_code: '3000' }] },
    });
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ id: 'a', is_primary: true });
    // A raw row with no id gets one minted; legacy city/postal_code keys map.
    expect(rows[1]!.id).toMatch(/^adr_/);
    expect(rows[1]).toMatchObject({ line1: 'No id', suburb: 'Legacy', postcode: '3000', is_primary: false });
  });

  it('returns [] for no bucket / a non-array bucket', () => {
    expect(clientAddresses({ custom_properties: {} })).toEqual([]);
    expect(clientAddresses({ custom_properties: { addresses: 'x' } })).toEqual([]);
    expect(clientAddresses(null)).toEqual([]);
  });

  it('guarantees exactly one primary: first flagged wins, else the first row', () => {
    expect(ensureOnePrimary([{ ...A, is_primary: false }, B, { ...C, is_primary: true }]).map((a) => a.is_primary)).toEqual([false, false, true]);
    expect(ensureOnePrimary([{ ...A, is_primary: true }, { ...B, is_primary: true }]).map((a) => a.is_primary)).toEqual([true, false]);
    expect(ensureOnePrimary([{ ...A, is_primary: false }, B]).map((a) => a.is_primary)).toEqual([true, false]);
    expect(primaryAddress({ custom_properties: { addresses: [{ ...A, is_primary: false }, { ...B, is_primary: true }] } })?.id).toBe('b');
  });
});

describe('formatAddress', () => {
  it('prints one line and skips empty parts', () => {
    expect(formatAddress(A)).toBe('12 Example Street, Level 3, Sampletown NSW 2000, Australia');
    expect(formatAddress({ line1: 'PO Box 99', postcode: '2000' })).toBe('PO Box 99, 2000');
    expect(formatAddress(undefined)).toBe('');
  });
});

describe('validateAddress', () => {
  it('requires line1 and accepts an empty postcode', () => {
    expect(validateAddress({ line1: '', postcode: '' })).toEqual({ line1: expect.any(String) });
    expect(validateAddress({ line1: '1 X St', postcode: '' })).toEqual({});
  });
  it('rejects an implausible postcode but allows alphanumerics', () => {
    expect(validateAddress({ line1: '1 X St', postcode: '2000' })).toEqual({});
    expect(validateAddress({ line1: '1 X St', postcode: 'SW1A 1AA' })).toEqual({});
    expect(validateAddress({ line1: '1 X St', postcode: '#' }).postcode).toBeTruthy();
    expect(validateAddress({ line1: '1 X St', postcode: '123456789012' }).postcode).toBeTruthy();
  });
});

describe('editor list operations', () => {
  it('addAddress makes the first row primary and later rows secondary', () => {
    const one = addAddress([], { line1: 'first' });
    expect(one).toHaveLength(1);
    expect(one[0]!.is_primary).toBe(true);
    const two = addAddress(one, { line1: 'second' });
    expect(two.map((a) => a.is_primary)).toEqual([true, false]);
    const three = addAddress(two, { line1: 'third', is_primary: true });
    expect(three.map((a) => a.is_primary)).toEqual([false, false, true]);
  });

  it('updateAddress patches one row by id without touching primary', () => {
    const rows = updateAddress([A, B], 'b', { line1: 'changed', postcode: '2999' });
    expect(rows[1]).toMatchObject({ id: 'b', line1: 'changed', postcode: '2999', is_primary: false });
    expect(rows[0]).toEqual(A);
  });

  it('setPrimaryAddress moves the flag and ignores an unknown id', () => {
    expect(setPrimaryAddress([A, B, C], 'c').map((a) => a.is_primary)).toEqual([false, false, true]);
    expect(setPrimaryAddress([A, B], 'zzz').map((a) => a.is_primary)).toEqual([true, false]);
  });

  it('removeAddress re-elects a primary when the primary is removed', () => {
    const rows = removeAddress([A, B, C], 'a');
    expect(rows.map((a) => a.id)).toEqual(['b', 'c']);
    expect(rows.map((a) => a.is_primary)).toEqual([true, false]);
    expect(removeAddress([A], 'a')).toEqual([]);
  });

  it('moveAddress swaps neighbours and is a no-op off either end', () => {
    expect(moveAddress([A, B, C], 'c', -1).map((a) => a.id)).toEqual(['a', 'c', 'b']);
    expect(moveAddress([A, B, C], 'a', 1).map((a) => a.id)).toEqual(['b', 'a', 'c']);
    expect(moveAddress([A, B, C], 'a', -1).map((a) => a.id)).toEqual(['a', 'b', 'c']);
    expect(moveAddress([A, B, C], 'c', 1).map((a) => a.id)).toEqual(['a', 'b', 'c']);
    // Reordering never changes which row is primary.
    expect(moveAddress([A, B, C], 'a', 1).find((a) => a.is_primary)?.id).toBe('a');
  });
});

describe('mirrorAddress', () => {
  it('writes the keys the upstream Contacts form reads, absent when empty', () => {
    expect(mirrorAddress(A)).toEqual({
      text: '12 Example Street, Level 3',
      street: '12 Example Street, Level 3',
      line1: '12 Example Street',
      line2: 'Level 3',
      city: 'Sampletown',
      state: 'NSW',
      postcode: '2000',
      country: 'Australia',
      label: 'Head office',
    });
    expect(mirrorAddress({ ...B, suburb: '', state: '', postcode: '', country: '', label: '' })).toEqual({
      text: '4 Sample Road',
      street: '4 Sample Road',
      line1: '4 Sample Road',
    });
    expect(mirrorAddress(undefined)).toBeNull();
  });
});

describe('saveClientDetails', () => {
  beforeEach(() => vi.mocked(updateContact).mockClear());

  it('sends ONE PATCH with merged custom_properties and the primary mirrored into address', async () => {
    const contact = {
      id: 'c1',
      custom_properties: { brand_color: '#2563eb', other_module: { keep: true } },
    };
    await saveClientDetails(contact, {
      name: ' Acme Holdings ',
      brand_color: '#DC2626',
      primary_email: 'hello@example.com',
      primary_phone: '',
      addresses: [{ ...A, is_primary: false }, { ...B, is_primary: true }],
    });
    expect(updateContact).toHaveBeenCalledTimes(1);
    const [id, body] = vi.mocked(updateContact).mock.calls[0]!;
    expect(id).toBe('c1');
    expect(body.company_name).toBe('Acme Holdings');
    expect(body.primary_email).toBe('hello@example.com');
    // '' clears (null), never an empty string the validator rejects.
    expect(body.primary_phone).toBeNull();
    expect(body.custom_properties).toMatchObject({
      brand_color: '#dc2626',
      other_module: { keep: true },
    });
    const stored = body.custom_properties!.addresses as ClientAddress[];
    expect(stored.map((a) => [a.id, a.is_primary])).toEqual([['a', false], ['b', true]]);
    expect(body.address).toMatchObject({ text: '4 Sample Road', city: 'Sampletown', postcode: '2000' });
  });

  it('leaves untouched fields out of the body and nulls address when the list is emptied', async () => {
    await saveClientDetails({ id: 'c2', custom_properties: {} }, { addresses: [] });
    const [, body] = vi.mocked(updateContact).mock.calls[0]!;
    expect(body).toEqual({ custom_properties: { addresses: [] }, address: null });
  });

  it('rejects a non-hex colour before any request', async () => {
    await expect(saveClientDetails({ id: 'c3', custom_properties: {} }, { brand_color: 'red' })).rejects.toThrow(/hex/);
    expect(updateContact).not.toHaveBeenCalled();
  });

  it('trims every address string so the stored row and the mirror agree', async () => {
    await saveClientDetails(
      { id: 'c4', custom_properties: {} },
      { addresses: [{ ...A, line1: '  9 Ninth Street  ', suburb: ' Sampletown ', postcode: ' 2000 ', is_primary: true }] },
    );
    const [, body] = vi.mocked(updateContact).mock.calls[0]!;
    const stored = body.custom_properties!.addresses as ClientAddress[];
    expect(stored[0]).toMatchObject({ line1: '9 Ninth Street', suburb: 'Sampletown', postcode: '2000' });
    expect(body.address).toMatchObject({ line1: '9 Ninth Street', text: '9 Ninth Street, Level 3', city: 'Sampletown', postcode: '2000' });
  });
});
