// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Rendering values inside course content, in the course locale.
//
// - Dates are written in words ("1 September 2026", "September 1, 2026",
//   "1. September 2026", "1 septembre 2026"), pinned to UTC so a date never
//   moves by a day in a western time zone. Nothing renders `M/d/yyyy`.
// - Money uses the course currency (or the field's own) and the course locale,
//   whatever the UI language is.
// - Values arrive as decimal strings and are formatted, never re-parsed into
//   anything the learner then types back.
//
// Chrome counters ("2/5") are not course content and use the UI locale; they
// do not go through this file.

import { formatCurrency } from '@/shared/lib/money';

import type { ValueKind } from './types';

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * A real calendar date as `YYYY-MM-DD`, or null. Refuses rollovers such as
 * `2026-02-31`, which `new Date` would quietly turn into 3 March.
 */
export function parseIsoDate(value: string): Date | null {
  const m = ISO_DATE.exec(value);
  if (!m) return null;
  const [, y, mo, d] = m;
  const date = new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d)));
  if (
    date.getUTCFullYear() !== Number(y) ||
    date.getUTCMonth() !== Number(mo) - 1 ||
    date.getUTCDate() !== Number(d)
  ) {
    return null;
  }
  return date;
}

function dateFormatter(locale: string): Intl.DateTimeFormat {
  try {
    return new Intl.DateTimeFormat(locale, { dateStyle: 'long', timeZone: 'UTC' });
  } catch {
    return new Intl.DateTimeFormat('en', { dateStyle: 'long', timeZone: 'UTC' });
  }
}

/** `2026-09-01` in words under the course locale. Not a date: returned unchanged. */
export function formatCourseDate(iso: string, locale: string): string {
  const date = parseIsoDate(iso);
  return date ? dateFormatter(locale).format(date) : iso;
}

// A date that stands alone: not glued to a letter, a digit or a hyphen, so
// ids like `INV-2026-09-01` and timestamps like `2026-09-01T10:00` stay as
// they are.
const ISO_DATE_IN_TEXT = /(?<![\p{L}\p{N}_-])(\d{4}-\d{2}-\d{2})(?![\p{L}\p{N}_-])/gu;

/** Replace every standalone ISO date in a course string with the date in words. */
export function renderCourseText(text: string, locale: string): string {
  if (!text) return text;
  return text.replace(ISO_DATE_IN_TEXT, (match: string) => formatCourseDate(match, locale));
}

function finiteNumber(value: string): number | null {
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(value.trim())) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function fractionDigitsOf(value: string): number {
  const dot = value.indexOf('.');
  return dot < 0 ? 0 : Math.min(value.length - dot - 1, 6);
}

/** A plain number in the course locale, keeping the decimals it was sent with. */
export function formatCourseNumber(value: string | number, locale: string): string {
  const text = String(value);
  const n = finiteNumber(text);
  if (n === null) return text;
  const digits = fractionDigitsOf(text.trim());
  try {
    return new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
  } catch {
    return text;
  }
}

/**
 * A percent value in the course locale. The value is already in percent
 * ("5.00" means 5 %), so it is formatted as a unit, not multiplied by 100.
 */
export function formatCoursePercent(value: string | number, locale: string): string {
  const text = String(value);
  const n = finiteNumber(text);
  if (n === null) return text;
  const digits = fractionDigitsOf(text.trim());
  // "5.00" reads as "5 %", "2.50" as "2.5 %": trailing zeros carry no meaning here.
  const shown = Math.min(digits, (text.trim().replace(/0+$/, '').split('.')[1] ?? '').length);
  try {
    return new Intl.NumberFormat(locale, {
      style: 'unit',
      unit: 'percent',
      minimumFractionDigits: shown,
      maximumFractionDigits: shown,
    }).format(n);
  } catch {
    return `${text} %`;
  }
}

/** Money in the course currency and locale. The locale is always explicit. */
export function formatCourseMoney(value: string | number, currency: string, locale: string): string {
  const text = String(value);
  if (finiteNumber(text) === null) return text;
  return formatCurrency(text, currency, locale);
}

export interface CourseValueContext {
  locale: string;
  /** The course currency; a field's own `currency` wins when it has one. */
  currency: string;
}

/**
 * Format any value the API sends with a `kind` (given items, related values,
 * readback values, observed values) for course content.
 */
export function formatCourseValue(
  value: string | null,
  kind: ValueKind,
  ctx: CourseValueContext,
  fieldCurrency?: string | null,
): string {
  if (value === null) return '';
  switch (kind) {
    case 'money':
      return formatCourseMoney(value, fieldCurrency || ctx.currency, ctx.locale);
    case 'percent':
      return formatCoursePercent(value, ctx.locale);
    case 'number':
      return formatCourseNumber(value, ctx.locale);
    case 'date':
      return formatCourseDate(value, ctx.locale);
    case 'text':
      return renderCourseText(value, ctx.locale);
  }
}
