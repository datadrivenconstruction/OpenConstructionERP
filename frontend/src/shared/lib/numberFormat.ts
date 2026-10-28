// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * numberFormat - Intl-backed value formatter shared by the Data Explorer
 * charts and any other surface that lets the user choose between a raw
 * number, a currency amount, or a percentage.
 *
 * Kept separate from `formatters.ts` (locale-aware currency/date helpers)
 * because the signature here is specifically "format one of three kinds"
 * - not "format currency" - so reusing it keeps the BarChart tooltip
 * axis label in sync with the chart value column.
 *
 * The fraction-digit pair goes through the shared clamp in
 * `fractionDigits.ts` rather than straight to `Intl`. Both ends used to be
 * passed explicitly (`?? 0` and `?? 2`), so a caller overriding only the
 * minimum produced `3 > 2` and an uncaught `RangeError` in a chart render
 * path - the same defect as issue #391 in `money.ts`, reached through
 * different defaults. Note that the engine's own ES2023 clamping does not
 * rescue this module the way it does a formatter that omits one end.
 */
import { getNumberLocale } from '@/stores/usePreferencesStore';
import {
  resolveFractionDigits,
  type FractionDigitOptions,
  type ResolvedFractionDigits,
} from './fractionDigits';

export type ValueFormatKind = 'number' | 'currency' | 'percent';

export interface FormatOptions extends FractionDigitOptions {
  /** ISO 4217 code, only used when kind === 'currency'. Defaults to EUR. */
  currency?: string;
  /** If true, a percent value is expected as a ratio (0.5 → 50%). When
   *  false the value is used verbatim (50 → 50%). Default false - the
   *  Data Explorer stores raw percentages. */
  percentAsRatio?: boolean;
  /**
   * Override minimum fraction digits. Defaults to 0 for every kind.
   * Overriding this end alone used to throw, because the maximum stayed at
   * its own default of 2; it is now reconciled against that default instead.
   */
  minimumFractionDigits?: number;
  /**
   * Override maximum fraction digits. Defaults to 2 for every kind. When
   * given it is the hard constraint: the minimum bends down to meet it.
   */
  maximumFractionDigits?: number;
}

/**
 * Fraction-digit policy when the caller says nothing: up to two digits, with
 * trailing zeros trimmed. Deliberately a *range* and not the currency's own
 * minor units, unlike `money.ts` - chart axes and Data Explorer cells mix
 * counts, areas and amounts in one column, and this is what they render
 * today. Giving the currency kind its natural minor units would be a nicer
 * number and a behaviour change, so it is not made here.
 */
const DEFAULT_FRACTION_DIGITS = { minimum: 0, maximum: 2 };

/** ISO 4217 code for the currency kind, with the historic EUR fallback. */
function resolveCurrencyCode(opts: FormatOptions): string {
  return opts.currency && /^[A-Z]{3}$/.test(opts.currency) ? opts.currency : 'EUR';
}

function cacheKey(
  kind: ValueFormatKind,
  locale: string,
  currency: string,
  digits: ResolvedFractionDigits,
): string {
  // Keyed on the *resolved* digits rather than the raw options, so callers
  // that spell the same formatter differently ({ min: 3 } and { min: 3,
  // max: 3 }) share one entry instead of building two identical formatters.
  return [
    kind,
    locale,
    currency,
    digits.minimumFractionDigits,
    digits.maximumFractionDigits,
  ].join('|');
}

const formatterCache = new Map<string, Intl.NumberFormat>();

function buildFormatter(
  kind: ValueFormatKind,
  locale: string,
  currency: string,
  digits: ResolvedFractionDigits,
): Intl.NumberFormat {
  const base: Intl.NumberFormatOptions = { ...digits };
  if (kind === 'currency') {
    base.style = 'currency';
    base.currency = currency;
  } else if (kind === 'percent') {
    base.style = 'percent';
  }

  try {
    return new Intl.NumberFormat(locale, base);
  } catch {
    // The digit pair is valid by construction and the currency code is regex
    // checked, which leaves a malformed locale tag as the only RangeError
    // Intl can still raise - and that one arrives from i18next, outside this
    // module. Retrying against the engine's default locale keeps the grouping
    // and the currency symbol that a hand-rolled string would lose. This
    // construction takes no locale and only pre-validated options, so it
    // cannot throw in turn.
    return new Intl.NumberFormat(undefined, base);
  }
}

function getFormatter(
  kind: ValueFormatKind,
  locale: string,
  currency: string,
  digits: ResolvedFractionDigits,
): Intl.NumberFormat {
  const key = cacheKey(kind, locale, currency, digits);
  const cached = formatterCache.get(key);
  if (cached) return cached;
  const fmt = buildFormatter(kind, locale, currency, digits);
  formatterCache.set(key, fmt);
  return fmt;
}

/** Format a numeric value for display in charts / tables.
 *
 *  - `number` - thousand-separator aware, max 2 fraction digits
 *  - `currency` - Intl currency with grouping (symbol + locale-aware)
 *  - `percent` - multiplies by 100 internally (Intl 'percent' style),
 *                unless `percentAsRatio: false`, in which case we format
 *                as number + '%' so stored percentages display unchanged.
 *
 *  Handles null, undefined, NaN, Infinity: returns '-'.
 *
 *  Never throws. A nonsensical fraction-digit override degrades to the
 *  default digit policy rather than taking down the chart it renders in.
 */
export function formatValue(
  value: number | null | undefined,
  kind: ValueFormatKind,
  opts: FormatOptions = {},
): string {
  if (value == null || !Number.isFinite(value)) return '-';
  const locale = getNumberLocale();
  const digits = resolveFractionDigits(opts, DEFAULT_FRACTION_DIGITS);

  if (kind === 'percent' && opts.percentAsRatio !== true) {
    // Value is already a percentage (e.g. 42.5 means 42.5%).
    return `${getFormatter('number', locale, '', digits).format(value)}%`;
  }

  const currency = kind === 'currency' ? resolveCurrencyCode(opts) : '';
  return getFormatter(kind, locale, currency, digits).format(value);
}

/** Convenience wrapper for chart tooltips / axis ticks - forwards to
 *  `formatValue` but tolerates non-numeric inputs from Recharts (string
 *  labels get echoed back verbatim). */
export function formatChartValue(
  value: number | string | null | undefined,
  kind: ValueFormatKind,
  opts: FormatOptions = {},
): string {
  if (typeof value === 'string') return value;
  return formatValue(value, kind, opts);
}
