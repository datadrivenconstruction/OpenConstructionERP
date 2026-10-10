import { describe, expect, it } from 'vitest';

import { buildContactPatch, contactFormData } from './ContactsPage';
import type { Contact } from './api';

/**
 * The contact address, which an e-invoice reads as the buyer's postal address.
 *
 * It is one JSON blob on the record and three fields on the form, and the
 * column is replaced rather than merged, so the flattening in both directions
 * is where a city or a post code goes missing. EN 16931 asks for them
 * separately (BT-52, BT-53) and XRechnung refuses an invoice lacking either,
 * which is why they are no longer part of one free-text line.
 */

function contact(address: Record<string, unknown> | null): Contact {
  return {
    id: 'c-1',
    contact_type: 'client',
    company_name: 'Stadtwerke Kiel',
    legal_name: null,
    vat_number: null,
    first_name: null,
    last_name: null,
    primary_email: null,
    primary_phone: null,
    website: null,
    country_code: 'DE',
    address,
    prequalification_status: null,
    payment_terms_days: null,
    notes: null,
  } as unknown as Contact;
}

describe('contactFormData', () => {
  it('splits a structured address into its three fields', () => {
    const form = contactFormData(contact({ text: 'Werftstrasse 14', postcode: '24143', city: 'Kiel' }));

    expect(form.address).toBe('Werftstrasse 14');
    expect(form.postcode).toBe('24143');
    expect(form.city).toBe('Kiel');
  });

  it('reads the spellings other parts of the platform store', () => {
    const form = contactFormData(contact({ street: 'Werftstrasse 14', postal_code: '24143', city: 'Kiel' }));

    expect(form.address).toBe('Werftstrasse 14');
    expect(form.postcode).toBe('24143');
  });

  it('leaves a legacy one-line address whole rather than splitting it', () => {
    // A guessed post code is exported as though someone confirmed it; a missing
    // one is reported to the user, so the line stays as written.
    const form = contactFormData(contact({ text: 'Werftstrasse 14, 24143 Kiel' }));

    expect(form.address).toBe('Werftstrasse 14, 24143 Kiel');
    expect(form.postcode).toBe('');
    expect(form.city).toBe('');
  });

  it('survives an address that is not an object', () => {
    expect(contactFormData(contact(null)).address).toBe('');
  });
});

describe('buildContactPatch', () => {
  const base = contactFormData(contact({ text: 'Werftstrasse 14', postcode: '24143', city: 'Kiel' }));

  it('rewrites the whole blob when only the city changed', () => {
    // The column is replaced, so a patch carrying the city alone would drop the
    // street and the post code.
    const patch = buildContactPatch({ ...base, city: 'Flensburg' }, base);

    expect(patch.address).toEqual({ text: 'Werftstrasse 14', postcode: '24143', city: 'Flensburg' });
  });

  it('sends nothing when no part of the address changed', () => {
    expect(buildContactPatch({ ...base }, base).address).toBeUndefined();
  });

  it('clears the blob to null when every part is emptied', () => {
    const patch = buildContactPatch({ ...base, address: '', postcode: '', city: '' }, base);

    expect(patch.address).toBeNull();
  });

  it('omits an emptied field rather than storing it blank', () => {
    // An empty string counts as an answer in the e-invoice merge and would stop
    // the invoice supplying its own value.
    const patch = buildContactPatch({ ...base, postcode: '' }, base);

    expect(patch.address).toEqual({ text: 'Werftstrasse 14', city: 'Kiel' });
  });
});

describe('party kind', () => {
  // Whether a contact is a person or a company decides whether a rating about
  // it is personal data, so "not stated" must stay distinct from either answer.
  const base = contactFormData(contact(null));

  it('reads a contact without the field as not stated', () => {
    expect(base.party_kind).toBe('');
  });

  it('sends the chosen kind and clears it back to null', () => {
    expect(buildContactPatch({ ...base, party_kind: 'natural_person' }, base).party_kind).toBe('natural_person');
    const company = { ...base, party_kind: 'legal_entity' as const };
    expect(buildContactPatch({ ...company, party_kind: '' }, company).party_kind).toBeNull();
  });

  it('leaves the field out when it did not change', () => {
    expect('party_kind' in buildContactPatch({ ...base }, base)).toBe(false);
  });
});
