import { describe, expect, it } from 'vitest';
import { isStandardPaymentTerms, paymentTermsToForm, paymentTermsToWire } from './paymentTerms';

describe('payment terms', () => {
  it('round-trips net days and cash', () => {
    expect(paymentTermsToForm('Net 45')).toBe('45');
    expect(paymentTermsToWire('45')).toBe('Net 45');
    expect(paymentTermsToForm('Cash')).toBe('cash');
    expect(paymentTermsToWire('cash')).toBe('Cash');
  });
  it('keeps text the form does not know', () => {
    const raw = '2% 10 net 30';
    expect(paymentTermsToForm(raw)).toBe(raw);
    expect(paymentTermsToWire(raw)).toBe(raw);
    expect(isStandardPaymentTerms(raw)).toBe(false);
  });
  it('defaults an empty value to 30 days', () => {
    expect(paymentTermsToForm(null)).toBe('30');
  });
});
