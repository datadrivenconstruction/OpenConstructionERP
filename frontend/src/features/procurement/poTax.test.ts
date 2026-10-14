import { describe, expect, it } from 'vitest';
import { initialPoTaxRate, poTaxFromRate, readPoTaxRate } from './poTax';

describe('purchase order VAT (#515)', () => {
  it("starts a new order at the project's default rate", () => {
    expect(initialPoTaxRate('5')).toBe('5');
    expect(initialPoTaxRate('21.00')).toBe('21');
    expect(initialPoTaxRate(null)).toBe('');
    expect(initialPoTaxRate('abc')).toBe('');
  });

  it('derives the tax from the net to the cent, half-up like the server', () => {
    expect(poTaxFromRate(1000, '5')).toBe('50.00');
    expect(poTaxFromRate(333.33, '7.5')).toBe('25.00');
    expect(poTaxFromRate(0.1 + 0.2, '10')).toBe('0.03');
    expect(poTaxFromRate(1000, '')).toBeNull();
  });

  it('refuses a rate outside 0 to 100', () => {
    expect(readPoTaxRate('150')).toBeNull();
    expect(readPoTaxRate('-1')).toBeNull();
    expect(readPoTaxRate('19%')).toBe(19);
  });
});
