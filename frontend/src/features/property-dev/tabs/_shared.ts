// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared constants, type aliases and tiny helpers used by the
 * per-tab modules under ``./tabs/*``.
 *
 * The originals still live in ``../PropertyDevPage.tsx`` for backwards
 * compatibility with the helpers/modals/drawers that have not yet been
 * extracted — those modules continue to reference the in-file copies
 * rather than this barrel. New tab files should import from here
 * instead.
 */

import type { BuyerStatus, PlotStatus, WarrantyStatus } from '../api';

// Order matters — arrow-key navigation walks the list in this order.
export const PROPDEV_TAB_IDS = [
  'overview',
  'developments',
  'phases',
  'blocks',
  'plots',
  'house_types',
  'leads',
  'buyers',
  'reservations',
  'spa',
  'payment_schedule',
  'brokers',
  'price_matrix',
  'escrow',
  'handovers',
  'warranty',
] as const;
export type Tab = (typeof PROPDEV_TAB_IDS)[number];

export const PLOT_STATUS_VARIANT: Record<
  PlotStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  planned: 'neutral',
  reserved: 'warning',
  under_construction: 'blue',
  ready: 'blue',
  sold: 'success',
  handed_over: 'success',
  held: 'warning',
  blocked: 'error',
};

export const PLOT_STATUS_COLOR: Record<PlotStatus, string> = {
  planned: 'bg-slate-200 text-slate-700 border-slate-300',
  reserved: 'bg-amber-100 text-amber-800 border-amber-300',
  under_construction: 'bg-sky-100 text-sky-800 border-sky-300',
  ready: 'bg-indigo-100 text-indigo-800 border-indigo-300',
  sold: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  handed_over: 'bg-emerald-200 text-emerald-900 border-emerald-400',
  held: 'bg-amber-200 text-amber-900 border-amber-400',
  blocked: 'bg-rose-100 text-rose-800 border-rose-300',
};

export const BUYER_STAGE_ORDER: BuyerStatus[] = [
  'lead',
  'reserved',
  'contracted',
  'completed',
];
export const BUYER_VARIANT: Record<
  BuyerStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  lead: 'neutral',
  reserved: 'warning',
  contracted: 'blue',
  completed: 'success',
  cancelled: 'error',
};

export const WARRANTY_VARIANT: Record<
  WarrantyStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  raised: 'warning',
  under_review: 'blue',
  accepted: 'success',
  rejected: 'error',
  closed: 'neutral',
};

export const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ─── helpers ─── */

export function toNumber(v: number | string | null | undefined): number {
  if (v == null) return 0;
  if (typeof v === 'number') return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

export function todayIso(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

export function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return null;
  const now = new Date();
  const diff = (target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24);
  return Math.ceil(diff);
}
