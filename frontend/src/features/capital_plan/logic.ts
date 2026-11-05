// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure helpers for the capital plan grid.

import type { CapitalItem, Envelope, EnvelopeBody } from './api';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/** A negative gap is a shortfall: the envelope does not cover the demand. */
export function gapTone(gap: string | number): 'short' | 'ok' | 'even' {
  const n = Number(gap);
  if (n < 0) return 'short';
  return n > 0 ? 'ok' : 'even';
}

/** Whole-unit money in the plan currency; a bare number when the code is unknown. */
export function formatMoney(value: string | number, currency: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(n);
  } catch {
    return n.toLocaleString(getNumberLocale(), { maximumFractionDigits: 0 });
  }
}

/** The start year after moving an item by whole years, never before 1900. */
export function shiftedStart(item: Pick<CapitalItem, 'start_year'>, delta: number): number {
  return Math.max(1900, item.start_year + delta);
}

/** Set one year to a single amount, keeping the other years and the source label of that year. */
export function withYearAmount(envelopes: Envelope[], year: number, amount: string): EnvelopeBody[] {
  const keep = envelopes
    .filter((e) => e.year !== year)
    .map((e) => ({ year: e.year, amount: e.amount, label: e.label }));
  const existing = envelopes.find((e) => e.year === year);
  return [...keep, { year, amount, label: existing?.label ?? '' }].sort((a, b) => a.year - b.year);
}

/** A year with several funding sources is shown as a sum and cannot be edited as one number. */
export function isSingleSource(envelopes: Envelope[], year: number): boolean {
  return envelopes.filter((e) => e.year === year).length <= 1;
}
