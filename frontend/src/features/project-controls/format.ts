// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Value formatting + currency-grouping helpers for the controls tiles.
 *
 * Money rule: a currency amount always carries its ISO code and portfolio
 * money is grouped per currency, never blended (mirrors the bi-dashboards
 * convention). Status colours map green/amber/red.
 */

import type { ControlsStatus } from './api';
import { fmtFixed } from '@/shared/lib/formatters';

export function formatControlsValue(
  rawValue: string | number,
  unit: string | null | undefined,
  currency?: string | null,
): string {
  const value = typeof rawValue === 'number' ? rawValue : Number(rawValue);
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  let formatted: string;
  if (abs >= 1_000_000) formatted = `${fmtFixed(value / 1_000_000, 2)}M`;
  else if (abs >= 1_000) formatted = `${fmtFixed(value / 1_000, 1)}k`;
  else if (Number.isInteger(value)) formatted = String(value);
  else formatted = fmtFixed(value, 2);

  switch (unit) {
    case 'percent':
      return `${formatted}%`;
    case 'days':
      return `${formatted}d`;
    case 'currency': {
      const code = (currency ?? '').trim().toUpperCase();
      return code ? `${code} ${formatted}` : formatted;
    }
    case 'ratio':
    case 'count':
    default:
      return formatted;
  }
}

/** Pull the ISO currency code a money KPI resolved, if any. */
export function kpiCurrency(
  breakdown: Record<string, unknown> | undefined,
): string | null {
  const c = breakdown?.['currency'];
  return typeof c === 'string' && c.trim() ? c.trim().toUpperCase() : null;
}

export function kpiByCurrency(
  breakdown: Record<string, unknown> | undefined,
): Array<{ currency: string; amount: number }> {
  const raw = breakdown?.['by_currency'];
  if (!raw || typeof raw !== 'object') return [];
  return Object.entries(raw as Record<string, unknown>)
    .map(([currency, v]) => ({
      currency,
      amount: typeof v === 'number' ? v : Number(v),
    }))
    .filter((e) => Number.isFinite(e.amount))
    .sort((a, b) => a.currency.localeCompare(b.currency));
}

export function kpiMultiCurrency(
  breakdown: Record<string, unknown> | undefined,
): boolean {
  return breakdown?.['multi_currency'] === true;
}

/** Tailwind utility classes for a traffic-light status. */
export function statusClasses(status: ControlsStatus): {
  dot: string;
  border: string;
  text: string;
} {
  switch (status) {
    case 'red':
      return {
        dot: 'bg-rose-500',
        border: 'border-l-rose-500',
        text: 'text-rose-600 dark:text-rose-400',
      };
    case 'amber':
      return {
        dot: 'bg-amber-500',
        border: 'border-l-amber-500',
        text: 'text-amber-600 dark:text-amber-400',
      };
    case 'green':
    default:
      return {
        dot: 'bg-emerald-500',
        border: 'border-l-emerald-500',
        text: 'text-content-primary',
      };
  }
}
