// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The words and figures of a payment certificate that the screen has to build
// itself: the sentence for a reason key, a rate or a fraction, and a decimal
// string printed inside a sentence.
//
// Reason sentences. A line with no figure carries a reason key from the closed
// vocabulary `ALL_REASON_KEYS` in `backend/app/core/payment_taxes/calc.py`.
// The server also sends the sentence, but only in the two languages a
// certificate prints in, so the screen words it from the key in the reader's
// own language and keeps the server's sentence as the fallback. The locale
// values under `hakedis.reason.*` are the printed sentences of
// `HAKEDIS_LABELS` in `backend/app/modules/contracts/hakedis_layout.py`, and
// `hakedisReasons.test.ts` fails when a key of the vocabulary has no sentence
// or when a sentence drifts from the printed one.
//
// Numbers. Every figure arrives as a decimal string and is formatted from the
// string: an engine that would convert it to a binary float is detected once,
// and the raw string is shown instead of a rounded figure.

import type { TFunction } from 'i18next';

import { isDecimalString } from '@/shared/lib/exactDecimal';
import { fmtDate, fmtList } from '@/shared/lib/formatters';
import { currencyFractionDigits } from '@/shared/lib/money';

let exactStrings: boolean | null = null;

function formatExact(formatter: Intl.NumberFormat, value: string): string {
  // TypeScript's Intl declaration predates the decimal-string overload.
  return (formatter.format as (input: number | string) => string)(value);
}

/** Whether `Intl.NumberFormat` keeps the digits of a decimal string. Older engines go through a float. */
function supportsExactStrings(): boolean {
  if (exactStrings !== null) return exactStrings;
  try {
    // Asked in the reader's own locale with Latin digits: only the digits are
    // compared, so the decimal mark of the locale does not matter.
    const probe = new Intl.NumberFormat(undefined, {
      useGrouping: false,
      maximumFractionDigits: 2,
      numberingSystem: 'latn',
    });
    exactStrings = formatExact(probe, '9007199254740993.01').replace(/\D/g, '') === '900719925474099301';
  } catch {
    exactStrings = false;
  }
  return exactStrings;
}

/** How many decimals a decimal string carries once trailing zeros are dropped. */
function significantDecimals(value: string): number {
  const fraction = value.split('.')[1] ?? '';
  return fraction.replace(/0+$/, '').length;
}

/**
 * A decimal string in the reader's number format, never rounded.
 *
 * At least `minDecimals` are printed, and every decimal the value carries
 * beyond that. A value that is not a canonical decimal string is returned as
 * it came.
 */
export function formatDecimalText(value: string | null | undefined, locale: string, minDecimals = 0): string {
  if (value === null || value === undefined) return '';
  if (!isDecimalString(value) || !supportsExactStrings()) return value;
  const digits = Math.min(20, Math.max(minDecimals, significantDecimals(value)));
  try {
    const formatter = new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
    return formatExact(formatter, value);
  } catch {
    return value;
  }
}

/** An amount inside a sentence: the currency's own decimals, no symbol. */
export function formatMoneyText(value: string | null | undefined, currency: string, locale: string): string {
  return formatDecimalText(value, locale, currencyFractionDigits(currency));
}

/** What a rate is stated as: a percent, or a fraction such as 4/10. */
export interface RateParts {
  rate_pct?: string | null;
  numerator?: number | string | null;
  denominator?: number | string | null;
}

/**
 * The rate or the fraction of a tax row, as the reader's language writes it.
 * Empty when the row states neither.
 */
export function rateText(t: TFunction, parts: RateParts, locale: string): string {
  const { numerator, denominator } = parts;
  const hasFraction =
    numerator !== null && numerator !== undefined && denominator !== null && denominator !== undefined;
  if (hasFraction && String(numerator) !== '' && String(denominator) !== '') {
    return t('hakedis.rate.fraction', {
      defaultValue: '{{numerator}}/{{denominator}}',
      numerator: String(numerator),
      denominator: String(denominator),
    });
  }
  if (parts.rate_pct !== null && parts.rate_pct !== undefined && parts.rate_pct !== '') {
    return t('hakedis.rate.percent', {
      defaultValue: '{{rate}}%',
      rate: formatDecimalText(parts.rate_pct, locale),
    });
  }
  return '';
}

/** `_MONEY_PARAMS` in `backend/app/modules/contracts/hakedis.py`: reason parameters that are amounts. */
const MONEY_PARAMS: readonly string[] = [
  'base',
  'expected',
  'work_value',
  'threshold',
  'measured',
  'cap',
  'computed',
  'stored',
  'stated',
];

export interface ReasonContext {
  currency: string;
  locale: string;
  /** Names a summary line by its key, for reasons that point at other lines. */
  lineName?: (key: string) => string;
}

/**
 * The sentence for one reason key, in the reader's language.
 *
 * Amounts among the parameters are printed in the reader's number format and
 * a date in their date format, the way the printed certificate does it in the
 * country's. A key the locale has no sentence for falls back to the server's
 * own sentence, and failing that to the generic "held" sentence naming the
 * key, so nothing is ever shown as a blank.
 */
export function reasonSentence(
  t: TFunction,
  key: string,
  params: Record<string, string>,
  context: ReasonContext,
  serverText?: string,
): string {
  const shown: Record<string, string> = { ...params };
  for (const name of MONEY_PARAMS) {
    const value = shown[name];
    if (value !== undefined) shown[name] = formatMoneyText(value, context.currency, context.locale);
  }
  if (shown.on !== undefined && /^\d{4}-\d{2}-\d{2}$/.test(shown.on)) shown.on = fmtDate(shown.on);
  const operands = shown.operands;
  if (operands !== undefined && context.lineName) {
    const name = context.lineName;
    shown.operands = fmtList(
      operands
        .split(',')
        .map((part) => part.trim())
        .filter((part) => part !== '')
        .map((part) => name(part)),
    );
  }
  const fallback =
    serverText ||
    t('hakedis.reason.other', {
      defaultValue: 'Held: {{reason}}.',
      reason: key,
    });
  if (!key) return fallback;
  return t(`hakedis.reason.${key}`, { ...shown, defaultValue: fallback });
}

/**
 * Reasons that only pass on another line's hold. `_DERIVED_REASONS` in
 * `hakedis.py`: such a line needs nothing done to it, its operand does.
 */
export const DERIVED_REASONS: readonly string[] = ['operand_held', 'base_held'];

/**
 * Reasons that belong to the stored tax set as a whole. Every tax line of the
 * certificate carries the same one, and one action resolves them all.
 */
export const TAX_SET_REASONS: readonly string[] = [
  'module_absent',
  'provider_failed',
  'taxes_stale',
  'taxes_outdated',
  'taxes_not_stored',
];
