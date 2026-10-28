// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Numbers and dates of the logistics plan, through the shared formatters.

import { fmtDate, fmtNumber } from '@/shared/lib/formatters';

import { decimalsOf } from './rules';
import { tx, type TFn } from './texts';

/** A decimal string in the reader's number format, with the decimals it carries; null when there is no value. */
export function num(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || value === '') return null;
  return fmtNumber(value, decimalsOf(value));
}

/** Today as the reader's own calendar day, for the date a new entry starts with. */
export function localToday(): string {
  const d = new Date();
  const two = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
}

export function day(iso: string | null | undefined): string | null {
  return iso ? fmtDate(iso) : null;
}

/** A point in time with its hour: on the site clock when the zone is known, else in the reader's own zone. */
export function when(iso: string | null | undefined, language: string, zone?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  try {
    return new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short', timeZone: zone || undefined }).format(d);
  } catch {
    // A zone the browser does not know.
    return new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(d);
  }
}

/** Two ends of a period as one phrase; one end alone when the other is open. */
export function span(t: TFn, from: string | null, to: string | null): string | null {
  if (from && to) return tx(t, 'range', { from, to });
  return from ?? to;
}

export function m2(t: TFn, value: string | number | null | undefined): string | null {
  const text = num(value);
  return text === null ? null : tx(t, 'm2', { value: text });
}

export function withUnit(t: TFn, value: string | number | null | undefined, unit: string): string | null {
  const text = num(value);
  if (text === null) return null;
  return unit ? tx(t, 'with_unit', { value: text, unit }) : text;
}
