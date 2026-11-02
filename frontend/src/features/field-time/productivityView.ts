// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pure helpers for the productivity tab: periods, number display, light colours. */

import type { ProductivityLight } from './productivityApi';

export type PeriodPreset = 'this_week' | 'last_week' | 'last_4_weeks' | 'month';

function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function monday(d: Date): Date {
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const shift = (out.getDay() + 6) % 7;
  out.setDate(out.getDate() - shift);
  return out;
}

/** Inclusive ISO date range for a preset, anchored on `today` (local time). */
export function periodFor(preset: PeriodPreset, today: Date = new Date()): { from: string; to: string } {
  const mon = monday(today);
  if (preset === 'this_week') {
    const sun = new Date(mon);
    sun.setDate(mon.getDate() + 6);
    return { from: iso(mon), to: iso(sun) };
  }
  if (preset === 'last_week') {
    const from = new Date(mon);
    from.setDate(mon.getDate() - 7);
    const to = new Date(mon);
    to.setDate(mon.getDate() - 1);
    return { from: iso(from), to: iso(to) };
  }
  if (preset === 'last_4_weeks') {
    const from = new Date(mon);
    from.setDate(mon.getDate() - 21);
    const to = new Date(mon);
    to.setDate(mon.getDate() + 6);
    return { from: iso(from), to: iso(to) };
  }
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  const last = new Date(today.getFullYear(), today.getMonth() + 1, 0);
  return { from: iso(first), to: iso(last) };
}

/** A decimal string for display with at most `digits` decimals; null shows a dash. */
export function fmtNum(raw: string | null | undefined, digits = 1, locale?: string): string {
  if (raw === null || raw === undefined || raw === '') return '-';
  const n = Number(raw);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString(locale, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

/** Factor as a percentage of the norm: 1.2 -> "120%". */
export function fmtFactorPct(raw: string | null | undefined, locale?: string): string {
  if (raw === null || raw === undefined || raw === '') return '-';
  const n = Number(raw);
  if (!Number.isFinite(n)) return '-';
  return `${Math.round(n * 100).toLocaleString(locale)}%`;
}

export const LIGHT_DOT: Record<ProductivityLight, string> = {
  green: 'bg-emerald-500',
  amber: 'bg-amber-400',
  red: 'bg-rose-500',
  grey: 'bg-gray-300 dark:bg-gray-600',
};

/** Height in percent (0-100) of a weekly trend bar against the busiest week. */
export function barHeight(raw: string | null | undefined, max: number): number {
  const n = Number(raw ?? 0);
  if (!Number.isFinite(n) || n <= 0 || max <= 0) return 0;
  return Math.max(4, Math.round((n / max) * 100));
}
