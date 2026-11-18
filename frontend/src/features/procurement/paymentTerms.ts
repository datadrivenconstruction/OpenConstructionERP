/**
 * Payment terms of a purchase order. The wire value is a sentence: `Cash` for
 * immediate payment on delivery, `Net 30` for days. A value the form does not
 * know (typed through the API or an import) is kept verbatim so opening and
 * saving an order never rewrites it.
 */
export const NET_DAY_OPTIONS = ['7', '15', '30', '45', '60', '90'] as const;
export const CASH_TERMS = 'cash';

/** Form value for a stored sentence: 'cash', a day count, or the raw text. */
export function paymentTermsToForm(stored: string | null | undefined): string {
  const text = (stored ?? '').trim();
  if (!text) return '30';
  if (/^(cash|cod|immediate)/i.test(text)) return CASH_TERMS;
  const net = text.match(/^net\s*(\d{1,3})$/i);
  if (net) return String(Number(net[1]));
  return text;
}

/** The sentence stored for a form value. */
export function paymentTermsToWire(value: string): string {
  if (value === CASH_TERMS) return 'Cash';
  if (/^\d{1,3}$/.test(value)) return `Net ${value}`;
  return value;
}

/** True when the value is one of the select's built-in choices. */
export function isStandardPaymentTerms(value: string): boolean {
  return value === CASH_TERMS || (NET_DAY_OPTIONS as readonly string[]).includes(value);
}
