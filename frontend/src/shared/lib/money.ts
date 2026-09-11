// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Canonical money primitives for the Decimal-as-string backend contract.
 *
 * The backend serialises every monetary value as a JSON *string* (a
 * `decimal.Decimal` rendered verbatim, e.g. `"1234.56"`) so large totals
 * round-trip without float precision loss and stay locale-neutral. The
 * TypeScript response types frequently declare these fields as `number`,
 * which is a lie: at runtime they arrive as strings. Calling `.toFixed()`
 * on that string throws (`"…".toFixed is not a function`), and a binary
 * `+` concatenates instead of adding. That mismatch is the single most
 * common money bug in this codebase (hundreds of historical `.toFixed`
 * crash sites).
 *
 * `toNum` is the one safe coercion primitive: it accepts whatever the wire
 * actually delivers (string | number | null | undefined), and never returns
 * `NaN`/`Infinity` - those degrade to `0` so downstream arithmetic and
 * `Intl.NumberFormat` can never blow up or render "NaN".
 *
 * `formatCurrency` is the locale-aware display formatter built on top of it.
 * Unlike a naive formatter it never hard-falls-back to EUR: rendering a
 * USD/BRL/JPY amount with a Euro sign actively misinforms the operator, so
 * an unknown/blank currency yields a plain grouped number with no symbol.
 */
// The reader's number locale, not the UI language. A screen follows its
// reader, and the reader may have asked for a format their language does not
// imply. The preference answers 'auto' with the UI language, so a caller who
// never set one sees exactly what it saw before; only a reader who chose is
// newly obeyed here.
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { resolveFractionDigits } from './fractionDigits';

/** Options controlling the fraction-digit policy of {@link formatCurrency}. */
export interface FormatCurrencyOptions {
  /**
   * Minimum fraction digits. Defaults to the currency's natural minor units.
   * Out-of-range and non-finite values are clamped rather than forwarded, so
   * a bad caller degrades the output instead of throwing.
   */
  minimumFractionDigits?: number;
  /**
   * Maximum fraction digits. Defaults to the currency's natural minor units.
   * When given, it is the hard constraint: the minimum bends down to meet it.
   */
  maximumFractionDigits?: number;
  /**
   * Sign policy, forwarded to `Intl` verbatim.
   *
   * It belongs here rather than at the call site because the locale decides
   * where the mark goes and a hand-written `+` is in front for everyone.
   * `Intl` places it according to the locale's own pattern.
   *
   * What it does not do is keep the sign on the same line as the figure. `+`
   * and `$` are both prefix-numeric under the Unicode line-breaking algorithm
   * and only one prefix may open an unbreakable numeric run, so the break
   * between them is legal whichever way the string was assembled - the
   * rendered characters are identical. Forbidding it is the cell's job, and
   * the call sites on the change-order register say `whitespace-nowrap`.
   */
  signDisplay?: Intl.NumberFormatOptions['signDisplay'];
}

const CURRENCY_CODE_RE = /^[A-Z]{3}$/;

/** Fraction digits used when there is no usable currency code. */
const PLAIN_FRACTION_DIGITS = 2;

/**
 * Natural minor-unit count per ISO 4217 code, as the running engine sees it.
 *
 * The engine is the answer for anything a person looks at, and it is now the
 * only answer: `MoneyDisplay` used to override it from a static ISO 4217
 * list this tree no longer carries, and the two disagreed on 16 codes
 * (AFN, ALL, COP, HUF, IDR, IQD, IRR, KPW, LAK, LBP, MGA, MMK, PKR, SOS, SYP,
 * YER) where CLDR says zero decimals and the list says two. That is not a
 * contest between two tables, it is a contest between a table and a reader: a
 * Hungarian does not write forints with fillér, so "1.234,00 Ft" was the list
 * arguing with the person reading it.
 *
 * ISO is right about the other half of the question. An invoice under EN
 * 16931 and any payment file declare an amount to a bank and a tax office,
 * whose authority is ISO 4217 and not the locale of whoever is looking, and
 * nothing on a screen is one of those. That half is written down where a
 * document is actually assembled, in `money_decimals` in the backend einvoice
 * rules, because a rule kept next to code that cannot act on it is a
 * comment rather than a rule.
 *
 * Cached by code alone - currency digits come from CLDR `currencyData` and do
 * not vary by locale, so keying on the locale would only multiply entries.
 */
const naturalDigitsCache = new Map<string, number>();

function naturalFractionDigits(code: string): number {
  const cached = naturalDigitsCache.get(code);
  if (cached !== undefined) return cached;
  let digits = PLAIN_FRACTION_DIGITS;
  try {
    // `maximumFractionDigits` is optional in the resolved options because a
    // significant-digits formatter reports no fraction bounds at all. This one
    // never asks for significant digits, so the fallback is unreachable in
    // practice and only there to keep the value a plain number.
    // The one hardcoded locale in this file, and it is not a display locale.
    // Nothing formatted here reaches a reader: the call asks the engine a
    // question about the CURRENCY, and how many minor units a currency has is
    // a property of the currency. CLDR keeps it in `currencyData`, which is
    // not keyed by locale at all, so every tag returns the same number and
    // 'en-US' is simply the one guaranteed present on a host built with a
    // trimmed ICU. Reading the reader's locale here would be the bug it looks
    // like the fix for.
    const resolved = new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: code,
    }).resolvedOptions();
    digits = resolved.maximumFractionDigits ?? PLAIN_FRACTION_DIGITS;
  } catch {
    // A well-formed but unknown code never lands here (Intl treats it as a
    // two-decimal currency); this only guards a host with no currency data.
  }
  naturalDigitsCache.set(code, digits);
  return digits;
}

/**
 * Minor units of `code`, for callers that render money themselves.
 *
 * `formatCurrency` is the right answer whenever the caller can hand over the
 * whole amount, because it also places the symbol and groups the digits. Some
 * surfaces cannot: a table that right-aligns a mono column and prints the ISO
 * code in its own `<span>` would render the code twice if it switched. Those
 * still need the one thing they cannot derive - how many decimals this
 * currency actually has - and reaching for a literal `2` is what puts
 * `82000.00 CLP` in front of a Chilean estimator. The Chilean peso, the yen
 * and the won have no minor unit at all, so the cents are not merely
 * redundant, they are a quantity the currency cannot express.
 *
 * Reads the same CLDR table `formatCurrency` reads, so a value formatted
 * through either route shows the same number of decimals.
 *
 * @param currency ISO 4217 code; blank or malformed yields the plain default.
 * @returns Fraction digits to use for both the minimum and the maximum.
 */
export function currencyFractionDigits(currency?: string | null): number {
  const code = (currency || '').trim().toUpperCase();
  return CURRENCY_CODE_RE.test(code) ? naturalFractionDigits(code) : PLAIN_FRACTION_DIGITS;
}

/**
 * Coerce a backend money value to a finite `number`, NaN-guarded.
 *
 * Accepts the Decimal-as-string the wire actually carries as well as a
 * genuine `number`. `null`, `undefined`, empty string, and any value that
 * does not parse to a finite number all collapse to `0` - never `NaN` or
 * `Infinity`, so callers can safely do arithmetic and `.toFixed()` on the
 * result.
 *
 * @param v The raw value (string | number | null | undefined).
 * @returns A finite number (`0` when the input is missing or unparseable).
 */
export function toNum(v: string | number | null | undefined): number {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Format a monetary value for display in the current (or given) locale.
 *
 * Coerces `v` via {@link toNum} first, so a Decimal-as-string is safe input.
 *
 * - A valid ISO 4217 `currency` renders with its symbol and (by default)
 *   its own minor-unit count (2 for EUR/USD, 0 for JPY, 3 for KWD…).
 * - A blank / unknown / malformed `currency` renders a plain grouped number
 *   with no symbol - never a wrong-currency symbol.
 * - `options` overrides the fraction-digit policy (e.g. whole-number
 *   summaries pass `{ maximumFractionDigits: 0 }`). A one-sided or inverted
 *   override is reconciled with the currency's own minor units before it
 *   reaches `Intl` - see {@link resolveFractionDigits}.
 * - This never throws, for any input. Callers render money inside React
 *   components, where a `RangeError` costs the whole page rather than one
 *   cell, so a hand-rolled string backs up the `Intl` call as well.
 *
 * @param v The value (Decimal-string or number).
 * @param currency Optional ISO 4217 code.
 * @param locale Optional BCP-47 locale tag; defaults to the active UI locale.
 * @param options Optional fraction-digit overrides.
 */

/**
 * Compact money for tiles, badges and chart axes: "203,1 Mio. €" in German,
 * "€203.1M" in English, "2.0億円" in Japanese.
 *
 * Four screens grew their own version of this and every one of them wrote
 * `.toFixed(1)` and an English `M`, so a German cost report printed
 * "203.1M EUR" - a decimal point where that reader expects a thousands
 * separator, and a magnitude letter their language does not use. The
 * engine's own compact notation knows both, per locale, and the currency
 * arrives as a symbol rather than a bare code for the same reason
 * {@link formatCurrency} prefers one.
 *
 * Amounts under a thousand are not compacted - there is nothing to shorten -
 * and fall through to {@link formatCurrency} at whole-number precision,
 * which is the look the callers had.
 *
 * @param v Amount, string or number, as the wire delivers it.
 * @param currency ISO 4217 code. Blank or unknown renders a bare number.
 * @param locale Override for the current UI locale.
 */
export function formatCompactCurrency(
  v: string | number | null | undefined,
  currency?: string | null,
  locale?: string,
): string {
  const amount = toNum(v);
  const loc = locale || getNumberLocale();
  const code = (currency || '').trim().toUpperCase();
  const isValid = CURRENCY_CODE_RE.test(code);
  const whole = { minimumFractionDigits: 0, maximumFractionDigits: 0 };
  if (Math.abs(amount) < 1000) return formatCurrency(amount, code, loc, whole);
  try {
    return new Intl.NumberFormat(loc, {
      notation: 'compact',
      compactDisplay: 'short',
      minimumFractionDigits: 0,
      maximumFractionDigits: 1,
      ...(isValid ? { style: 'currency' as const, currency: code } : {}),
    }).format(amount);
  } catch {
    // A malformed locale tag, the same case formatCurrency guards against.
    return formatCurrency(amount, code, loc, whole);
  }
}

export function formatCurrency(
  v: string | number | null | undefined,
  currency?: string | null,
  locale?: string,
  options?: FormatCurrencyOptions,
): string {
  const amount = toNum(v);
  const loc = locale || getNumberLocale();
  const code = (currency || '').trim().toUpperCase();
  const isValid = CURRENCY_CODE_RE.test(code);

  // Both ends are always resolved here rather than left for Intl to default,
  // so the engine's own currency table can never combine with a one-sided
  // caller override into an invalid pair. Money's default is a point rather
  // than a range: an amount in a two-decimal currency shows both decimals or
  // it does not look like money, so the floor and the ceiling are the same.
  const natural = isValid ? naturalFractionDigits(code) : PLAIN_FRACTION_DIGITS;
  const digits = resolveFractionDigits(options, { minimum: natural, maximum: natural });

  try {
    return new Intl.NumberFormat(loc, {
      ...(isValid ? { style: 'currency' as const, currency: code } : {}),
      ...(options?.signDisplay ? { signDisplay: options.signDisplay } : {}),
      ...digits,
    }).format(amount);
  } catch {
    // Defence in depth. The digit pair is now valid by construction, which
    // leaves a malformed `locale` tag as the only RangeError Intl can still
    // raise here, and that one arrives from outside this module. `toFixed` is
    // safe because the ceiling is already inside [0, 20] and `toNum`
    // guarantees a finite amount. The code is appended only when it is a real
    // ISO 4217 code - never echo back a malformed one as if it were a unit.
    // The sign policy is applied here too: a caller that asked for an explicit
    // plus asked for it because the alternative was writing one by hand, and a
    // fallback that quietly drops it hands that problem straight back.
    const magnitude = options?.signDisplay === 'never' ? Math.abs(amount) : amount;
    const text = `${fallbackSign(amount, options?.signDisplay)}${magnitude.toFixed(digits.maximumFractionDigits)}`;
    return isValid ? `${text} ${code}` : text;
  }
}

/**
 * The leading `+` the `Intl` path would have written, for the hand-rolled
 * fallback above. Negative amounts already carry their minus from `toFixed`,
 * and every policy other than an explicit plus writes nothing here.
 */
function fallbackSign(amount: number, signDisplay: Intl.NumberFormatOptions['signDisplay']): string {
  if (amount < 0) return '';
  if (signDisplay === 'always') return '+';
  if (signDisplay === 'exceptZero') return amount > 0 ? '+' : '';
  return '';
}
