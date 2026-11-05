export interface BillingFields {
  billingSame: boolean;
  billingStreet: string;
  billingPostcode: string;
  billingCity: string;
  billingState: string;
  billingCountry: string;
}

/** The billing address blob, or `null` when it is the premises address. */
export function billingPayload(form: BillingFields): Record<string, string> | null {
  if (form.billingSame) return null;
  const stored: Record<string, string> = {};
  if (form.billingStreet) stored.street = form.billingStreet;
  if (form.billingPostcode) stored.postcode = form.billingPostcode;
  if (form.billingCity) stored.city = form.billingCity;
  if (form.billingState) stored.state = form.billingState;
  if (form.billingCountry) stored.country = form.billingCountry;
  return Object.keys(stored).length > 0 ? stored : null;
}
