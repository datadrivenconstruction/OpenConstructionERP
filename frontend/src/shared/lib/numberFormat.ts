/**
 * numberFormat — Intl-backed value formatter shared by the Data Explorer
 * charts and any other surface that lets the user choose between a raw
 * number, a currency amount, or a percentage.
 *
 * Kept separate from `formatters.ts` (locale-aware currency/date helpers)
 * because the signature here is specifically "format one of three kinds"
 * — not "format currency" — so reusing it keeps the BarChart tooltip
 * axis label in sync with the chart value column.
 */
import { getIntlLocale } from './formatters';

export type ValueFormatKind = 'number' | 'currency' | 'percent';

export interface FormatOptions {
  /** ISO 4217 code, only used when kind === 'currency'. Defaults to EUR. */
  currency?: string;
  /** If true, a percent value is expected as a ratio (0.5 → 50%). When
   *  false the value is used verbatim (50 → 50%). Default false — the
   *  Data Explorer stores raw percentages. */
  percentAsRatio?: boolean;
  /** Override minimum fraction digits. Defaults depend on kind. */
  minimumFractionDigits?: number;
  /** Override maximum fraction digits. Defaults depend on kind. */
  maximumFractionDigits?: number;
}

function cacheKey(kind: ValueFormatKind, locale: string, opts: FormatOptions): string {
  return [
    kind,
    locale,
    opts.currency ?? '',
    opts.minimumFractionDigits ?? -1,
    opts.maximumFractionDigits ?? -1,
  ].join('|');
}

const formatterCache = new Map<string, Intl.NumberFormat>();

function buildFormatter(
  kind: ValueFormatKind,
  locale: string,
  opts: FormatOptions,
): Intl.NumberFormat {
  const base: Intl.NumberFormatOptions = {};
  switch (kind) {
    case 'currency':
      base.style = 'currency';
      base.currency =
        opts.currency && /^[A-Z]{3}$/.test(opts.currency) ? opts.currency : 'EUR';
      base.minimumFractionDigits = opts.minimumFractionDigits ?? 0;
      base.maximumFractionDigits = opts.maximumFractionDigits ?? 2;
      break;
    case 'percent':
      base.style = 'percent';
      base.minimumFractionDigits = opts.minimumFractionDigits ?? 0;
      base.maximumFractionDigits = opts.maximumFractionDigits ?? 2;
      break;
    case 'number':
    default:
      base.minimumFractionDigits = opts.minimumFractionDigits ?? 0;
      base.maximumFractionDigits = opts.maximumFractionDigits ?? 2;
      break;
  }
  return new Intl.NumberFormat(locale, base);
}

function getFormatter(
  kind: ValueFormatKind,
  locale: string,
  opts: FormatOptions,
): Intl.NumberFormat {
  const key = cacheKey(kind, locale, opts);
  const cached = formatterCache.get(key);
  if (cached) return cached;
  const fmt = buildFormatter(kind, locale, opts);
  formatterCache.set(key, fmt);
  return fmt;
}

/** Format a numeric value for display in charts / tables.
 *
 *  - `number` — thousand-separator aware, max 2 fraction digits
 *  - `currency` — Intl currency with grouping (symbol + locale-aware)
 *  - `percent` — multiplies by 100 internally (Intl 'percent' style),
 *                unless `percentAsRatio: false`, in which case we format
 *                as number + '%' so stored percentages display unchanged.
 *
 *  Handles null, undefined, NaN, Infinity: returns '-'.
 */
export function formatValue(
  value: number | null | undefined,
  kind: ValueFormatKind,
  opts: FormatOptions = {},
): string {
  if (value == null || !Number.isFinite(value)) return '-';
  const locale = getIntlLocale();

  if (kind === 'percent' && opts.percentAsRatio !== true) {
    // Value is already a percentage (e.g. 42.5 means 42.5%).
    const fmt = getFormatter('number', locale, opts);
    return `${fmt.format(value)}%`;
  }

  const fmt = getFormatter(kind, locale, opts);
  return fmt.format(value);
}

/** Convenience wrapper for chart tooltips / axis ticks — forwards to
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
