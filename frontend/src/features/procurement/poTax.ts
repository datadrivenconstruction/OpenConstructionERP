/**
 * VAT on a purchase order (#515).
 *
 * An order carries a rate, and its tax follows the net. A new order starts at
 * the project's default VAT rate; a buyer who types the tax as an amount
 * instead clears the rate, and the amount is kept as typed. The server derives
 * the stored tax from the rate with Decimal arithmetic; this preview only has
 * to agree with it to the cent.
 */

/** A rate the field accepts: a number from 0 to 100, else null. */
export function readPoTaxRate(raw: string | number | null | undefined): number | null {
  if (raw == null) return null;
  const text = String(raw).trim().replace(/%$/, '').trim();
  if (text === '') return null;
  const n = Number(text);
  return Number.isFinite(n) && n >= 0 && n <= 100 ? n : null;
}

/** The rate a new order starts with: the project's default, or none. */
export function initialPoTaxRate(projectDefault: string | number | null | undefined): string {
  const n = readPoTaxRate(projectDefault);
  return n == null ? '' : String(Number(n.toFixed(4)));
}

/** Tax on a net at a rate, half-up to the cent, as the field shows it. */
export function poTaxFromRate(subtotal: number, rate: string): string | null {
  const r = readPoTaxRate(rate);
  if (r == null || !Number.isFinite(subtotal)) return null;
  // Scale to integer cents before rounding so 333.33 x 7.5% lands on 25.00,
  // the same cent the server's ROUND_HALF_UP gives.
  const cents = Math.round(Number(((subtotal * r) / 100 * 100).toPrecision(12)));
  return (cents / 100).toFixed(2);
}
