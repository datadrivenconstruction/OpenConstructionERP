// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Display helpers for captured quotes: locale-aware numbers and confidence bands. */

import { getNumberLocale } from '@/stores/usePreferencesStore';
import { LOW_CONFIDENCE, type Anchor } from './api';

export type ConfidenceBand = 'high' | 'medium' | 'low';

export function confidenceBand(value: number | null | undefined): ConfidenceBand {
  const v = value ?? 0;
  if (v >= 0.85) return 'high';
  if (v >= LOW_CONFIDENCE) return 'medium';
  return 'low';
}

export const BAND_CLASS: Record<ConfidenceBand, string> = {
  high: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  low: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200',
};

/** Format a wire decimal ("1234.5") in the user's number locale; non-numbers pass through. */
export function formatDecimal(value: string | null | undefined, digits = 2, locale?: string): string {
  if (value === null || value === undefined || value === '') return '';
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return new Intl.NumberFormat(locale || getNumberLocale(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: Math.max(digits, 4),
  }).format(n);
}

/** Read a number typed in the user's locale ("1.234,5" or "1,234.5") back to a wire decimal. */
export function parseLocaleDecimal(text: string, locale?: string): string | null {
  const raw = text.trim().replace(/[\s  ']/g, '');
  if (!raw) return null;
  const parts = new Intl.NumberFormat(locale || getNumberLocale()).formatToParts(1234.5);
  const decimal = parts.find((p) => p.type === 'decimal')?.value ?? '.';
  const group = decimal === ',' ? '.' : ',';
  const normalised = raw.split(group).join('').replace(decimal, '.');
  return /^-?\d+(\.\d+)?$/.test(normalised) ? normalised : null;
}

/** Same anchor (one document line, cell row or page box)? */
export function sameAnchor(a: Anchor | null | undefined, b: Anchor | null | undefined): boolean {
  if (!a || !b) return false;
  if (a.line !== undefined) return a.line === b.line;
  if (a.sheet !== undefined) return a.sheet === b.sheet && a.row === b.row;
  return a.page === b.page && JSON.stringify(a.bbox) === JSON.stringify(b.bbox);
}
