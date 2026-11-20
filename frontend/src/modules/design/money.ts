// Design module (ERP side of the design editor link).
/** Money through the ERP's own formatter (number locale preference, currency symbol and placement). */
import { formatCurrency } from '@/shared/lib/money';

const WHOLE = { minimumFractionDigits: 0, maximumFractionDigits: 0 };

/** Totals and ranges: whole currency units; cents on a sum of estimated quantities are false precision. */
export function moneyWhole(v: string | number | null | undefined, currency?: string | null): string {
  if (v === null || v === undefined || v === '' || !Number.isFinite(Number(v))) return '–';
  return formatCurrency(v, currency ?? '', undefined, WHOLE);
}

/** Unit rates: the currency's own minor units. */
export function moneyExact(v: string | number | null | undefined, currency?: string | null, signed = false): string {
  if (v === null || v === undefined || v === '' || !Number.isFinite(Number(v))) return '–';
  return formatCurrency(v, currency ?? '', undefined, signed ? { signDisplay: 'exceptZero' } : undefined);
}

/** The project's currency: the estimate's own, else the project setting. */
export function pickCurrency(...c: (string | null | undefined)[]): string {
  return c.find((x) => !!x && x.trim() !== '')?.trim() ?? '';
}
