// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// fxDisplay.ts - display-only currency conversion for the cross-base
// compare view. This is deliberately NOT a finance module:
//
//   * The rate table is STATIC and hand-dated. There is no network call,
//     no live feed, no caching, no side effect. It exists so a user can
//     eyeball two cost bases quoted in different currencies on one rough
//     scale, nothing more.
//   * Every value it produces is an APPROXIMATE ESTIMATE. It must never be
//     written to a BOQ position, an Assembly rate, or any stored Decimal.
//     The wire contract keeps money as Decimal-as-string in its native
//     currency; this helper only ever feeds transient display state.
//   * Callers surface FX_RATES_AS_OF and an explicit "estimate" label so
//     the operator knows the numbers are indicative and dated. See
//     CrossBaseCompare.tsx.
//
// All conversion paths are guarded: unknown or zero source rates return
// null (never a guessed number), so a caller can distinguish "converted"
// from "cannot convert" and keep the native value visible.

/**
 * Date the indicative rate table was last hand-set (ISO-8601). Surfaced in
 * the UI so the estimate is honestly dated. Bump this whenever the numbers
 * below are refreshed.
 */
export const FX_RATES_AS_OF = '2026-01-02';

/**
 * Internal pivot currency. Rates are stored as "units of currency per 1 USD"
 * and every A -> B conversion routes through USD. USD is a maths pivot only;
 * it carries no special meaning in the UI.
 */
export const FX_PIVOT_CURRENCY = 'USD';

/**
 * Indicative mid-market rates: how many units of the currency equal 1 USD,
 * as of `FX_RATES_AS_OF`. Hand-set for rough visual comparison ONLY, never
 * for calculation of a real estimate. Frozen so a caller can never mutate
 * the shared table at runtime.
 */
export const FX_UNITS_PER_USD: Readonly<Record<string, number>> = Object.freeze({
  USD: 1,
  EUR: 0.92,
  GBP: 0.79,
  CHF: 0.88,
  CAD: 1.36,
  AUD: 1.52,
  NZD: 1.65,
  BRL: 5.0,
  MXN: 17.1,
  RUB: 90,
  AED: 3.67,
  CNY: 7.15,
  INR: 83,
  BGN: 1.8,
  CZK: 23,
  PLN: 3.95,
  RON: 4.58,
  SEK: 10.5,
  THB: 35,
  TRY: 34,
  VND: 25000,
  IDR: 15800,
  JPY: 150,
  KRW: 1350,
  NGN: 1500,
  ZAR: 18.5,
});

/** ISO 4217 codes (upper-cased) that have an indicative rate. */
export const SUPPORTED_FX_CURRENCIES: readonly string[] = Object.freeze(
  Object.keys(FX_UNITS_PER_USD),
);

/** Normalise a currency code: trim + upper-case, guarding null/undefined. */
function normCode(code: string | null | undefined): string {
  return (code || '').trim().toUpperCase();
}

/** True when we hold a usable (finite, positive) rate for `currency`. */
export function isFxSupported(currency: string | null | undefined): boolean {
  const rate = FX_UNITS_PER_USD[normCode(currency)];
  return typeof rate === 'number' && Number.isFinite(rate) && rate > 0;
}

export interface FxConversion {
  /** Converted numeric value in the target currency (a display estimate). */
  value: number;
  /** Target ISO 4217 code the value is expressed in. */
  currency: string;
  /** Date the underlying indicative rate table was set. */
  asOf: string;
}

/**
 * Convert `amount` from one currency to another using the static table.
 *
 * Returns null (never a guessed number) when:
 *   - `amount` is not a finite number,
 *   - either currency is unknown / unsupported,
 *   - the source rate is zero (divide-by-zero guard),
 *   - the maths produces a non-finite result.
 *
 * The result is an APPROXIMATE display estimate. Do not persist it, do not
 * feed it into a BOQ Decimal.
 */
export function convertAmount(
  amount: number,
  from: string | null | undefined,
  to: string | null | undefined,
): FxConversion | null {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return null;

  const fromCode = normCode(from);
  const toCode = normCode(to);
  const fromRate = FX_UNITS_PER_USD[fromCode];
  const toRate = FX_UNITS_PER_USD[toCode];

  // Guard unknown currencies and, critically, a zero/negative source rate
  // before it can reach the division below.
  if (!(typeof fromRate === 'number' && Number.isFinite(fromRate) && fromRate > 0)) return null;
  if (!(typeof toRate === 'number' && Number.isFinite(toRate) && toRate > 0)) return null;

  // Identity: same currency, no rounding drift.
  if (fromCode === toCode) {
    return { value: amount, currency: toCode, asOf: FX_RATES_AS_OF };
  }

  const inUsd = amount / fromRate; // fromRate > 0 is guaranteed above
  const converted = inUsd * toRate;
  if (!Number.isFinite(converted)) return null;

  return { value: converted, currency: toCode, asOf: FX_RATES_AS_OF };
}

/** Rank used only to break ties when picking a default target currency. */
function tieRank(code: string): number {
  if (code === 'USD') return 0;
  if (code === 'EUR') return 1;
  return 2;
}

/**
 * Choose a sensible target currency for the "one currency" view, given the
 * currencies actually present in the comparison.
 *
 * Preference order:
 *   1. The most frequently used FX-supported currency among `currencies`
 *      (comparing three EUR bases and one TRY base lands on EUR).
 *   2. USD, then EUR, as neutral pivots when counts tie.
 *   3. USD as the final fallback when nothing supported is present.
 *
 * Always returns a supported currency.
 */
export function pickDefaultTarget(currencies: Array<string | null | undefined>): string {
  const counts = new Map<string, number>();
  for (const c of currencies) {
    const code = normCode(c);
    if (!isFxSupported(code)) continue;
    counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  if (counts.size === 0) return FX_PIVOT_CURRENCY;

  let best = '';
  let bestCount = -1;
  for (const [code, n] of counts) {
    if (n > bestCount || (n === bestCount && tieRank(code) < tieRank(best))) {
      best = code;
      bestCount = n;
    }
  }
  return best || FX_PIVOT_CURRENCY;
}

/**
 * Target currencies to offer in the "one currency" selector: the supported
 * currencies present in the comparison first, then USD and EUR as neutral
 * pivots, de-duplicated. Never contains an unsupported code, so every option
 * is guaranteed convertible.
 */
export function targetCurrencyOptions(currencies: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  const add = (c: string | null | undefined) => {
    const code = normCode(c);
    if (!code || seen.has(code) || !isFxSupported(code)) return;
    seen.add(code);
    out.push(code);
  };
  for (const c of currencies) add(c);
  add('USD');
  add('EUR');
  return out;
}
