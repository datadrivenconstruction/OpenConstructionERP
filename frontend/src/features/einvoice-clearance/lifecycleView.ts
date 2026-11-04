// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure view helpers for the e-invoice card and list: stepper position, deadline
 * tone and wording, and the visibility gate. No React, so vitest covers them.
 */
import { getNumberLocale } from '@/stores/usePreferencesStore';
import type { BadgeVariant } from './documentStatus';
import type { DeadlineState, EInvoiceSetupRow, LifecycleAction, LifecycleDeadline } from './lifecycleApi';

export type Step = 'draft' | 'validated' | 'sent' | 'done' | 'accepted';

export const STEPS: readonly Step[] = ['draft', 'validated', 'sent', 'done', 'accepted'];

/** Index of the current step. `rejected` and `cancelled` sit on the step they left. */
export function stepIndex(status: string): number {
  switch (status) {
    case 'draft':
    case 'rejected':
      return 0;
    case 'validated':
    case 'queued':
      return 1;
    case 'submitted':
      return 2;
    case 'cleared':
    case 'reported':
    case 'cancelled':
    case 'corrected':
      return 3;
    case 'delivered':
    case 'accepted':
      return 4;
    default:
      return 0;
  }
}

export function deadlineVariant(state: DeadlineState | string): BadgeVariant {
  if (state === 'overdue') return 'error';
  if (state === 'warning') return 'warning';
  return 'neutral';
}

/** The largest whole unit of a duration, for Intl.RelativeTimeFormat. */
export function durationParts(seconds: number): { value: number; unit: 'day' | 'hour' | 'minute' } {
  const abs = Math.abs(seconds);
  if (abs >= 2 * 86400) return { value: Math.floor(abs / 86400), unit: 'day' };
  if (abs >= 3600) return { value: Math.floor(abs / 3600), unit: 'hour' };
  return { value: Math.max(1, Math.floor(abs / 60)), unit: 'minute' };
}

/** Localised duration such as "21 hours" / "21 Stunden" (no "in" / "ago"). */
export function formatDuration(seconds: number, locale: string): string {
  const { value, unit } = durationParts(seconds);
  try {
    return new Intl.NumberFormat(locale, { style: 'unit', unit, unitDisplay: 'long' }).format(value);
  } catch {
    // An unknown locale tag still gets a unit-correct string in the runtime default.
    return new Intl.NumberFormat(getNumberLocale(), { style: 'unit', unit, unitDisplay: 'long' }).format(value);
  }
}

/** The deadline the badge shows: the earliest one still open, else the most overdue. */
export function primaryDeadline(deadlines: LifecycleDeadline[]): LifecycleDeadline | null {
  if (!deadlines.length) return null;
  return [...deadlines].sort((a, b) => a.due_at.localeCompare(b.due_at))[0] ?? null;
}

/** The one primary button; download is always a secondary action. */
export function primaryAction(actions: LifecycleAction[]): LifecycleAction | null {
  return actions.find((a) => a !== 'download') ?? null;
}

/**
 * Visibility gate: the card and the Finance tabs show only when the tenant has
 * at least one e-invoicing market. `country` narrows it to one seller country.
 * Point this at market scope once that lands; the call sites stay the same.
 */
export function einvoiceVisible(rows: EInvoiceSetupRow[] | undefined, country?: string | null): boolean {
  if (!rows || rows.length === 0) return false;
  if (!country) return true;
  return rows.some((r) => r.country === country.toUpperCase());
}

/** Due-soon filter for the outbound list: warning or overdue. */
export function isDueSoon(deadline: LifecycleDeadline | null): boolean {
  return !!deadline && deadline.state !== 'ok';
}

/** Default period for the consolidated wizard: the month before `today`. */
export function lastMonth(today: Date): string {
  const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - 1, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}
