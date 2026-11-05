import { describe, expect, it } from 'vitest';
import { billingPayload, type BillingFields } from './billing';

const base = { billingSame: true, billingStreet: '', billingPostcode: '', billingCity: '', billingState: '', billingCountry: '' };

describe('billingPayload', () => {
  it('stores nothing while "Same as address" is ticked, even with a typed address', () => {
    expect(billingPayload({ ...base, billingStreet: 'Hauptstr. 1' } as BillingFields)).toBeNull();
  });

  it('stores only the filled parts once it is unticked', () => {
    const form = { ...base, billingSame: false, billingStreet: 'Hauptstr. 1', billingCity: 'Berlin' } as BillingFields;
    expect(billingPayload(form)).toEqual({ street: 'Hauptstr. 1', city: 'Berlin' });
  });

  it('stores nothing for an unticked but empty address', () => {
    expect(billingPayload({ ...base, billingSame: false } as BillingFields)).toBeNull();
  });
});
