// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Rework cost on a punch item: what it will cost to put the snag right.
 *
 * The add form and the item drawer both take the figure, so the typed-amount
 * grammar and the currency rule live here once. The amount is money, so it is
 * a text field run through the shared decimal parser (a number input drops a
 * typed comma and turns 48,60 into 4860), and it crosses the wire as a dot
 * decimal string. The currency is the project's: the backend stamps USD on
 * anything that arrives without one, which on a euro job would file the cost
 * under the wrong currency in the QMS cost of poor quality.
 */

import { formatCurrency } from '@/shared/lib/money';
import {
  normalizeDecimalSeparators,
  parseMoneyInput,
  stripCurrencySigns,
} from '@/shared/lib/parseDecimal';

/** The project's currency as an ISO code, or '' when the project has none set. */
export function projectCurrencyCode(raw: string | null | undefined): string {
  const code = (raw ?? '').trim().toUpperCase();
  return /^[A-Z]{3}$/.test(code) ? code : '';
}

export type ReworkCostInput =
  /** `value` is null for an empty field: the item is not priced, which is not zero. */
  | { ok: true; value: string | null }
  | { ok: false };

/** Read a typed rework cost. Accepts `1.250,50`, `1,250.50`, `€ 1250`; refuses negatives. */
export function parseReworkCostInput(raw: string): ReworkCostInput {
  const text = stripCurrencySigns(raw);
  if (text === '') return { ok: true, value: null };
  const n = parseMoneyInput(text);
  if (n === null || n < 0) return { ok: false };
  // The normalised text, not String(n): re-serialising through a float is
  // the precision loss the string wire format exists to avoid.
  return { ok: true, value: normalizeDecimalSeparators(text) };
}

/**
 * The stored amount as the edit box should show it. Rows saved before the API
 * stopped writing exponents can hold `9E+2`; show those as `900`.
 */
export function reworkCostForInput(stored: string | null | undefined): string {
  if (stored == null) return '';
  return /e/i.test(stored) ? String(Number(stored)) : stored;
}

/** The cost in the currency it was recorded in, or null when the item is not priced. */
export function formatReworkCost(item: {
  rework_cost: string | null | undefined;
  rework_cost_currency: string | null | undefined;
}): string | null {
  if (item.rework_cost == null || item.rework_cost.trim() === '') return null;
  return formatCurrency(item.rework_cost, item.rework_cost_currency);
}
