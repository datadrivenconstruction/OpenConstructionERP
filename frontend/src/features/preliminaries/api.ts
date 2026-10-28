// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers and pure preview math for the Preliminaries (general conditions)
 * estimator.
 *
 * Every path is built from BASE ('/v1/preliminaries'); apiGet / apiPost already
 * prepend '/api', so we never write '/api/v1' here. Every monetary value crosses
 * the wire as a Decimal-as-string (e.g. "3500.00"), never a number: format it for
 * display with formatCurrency from '@/shared/lib/money' and never call .toFixed
 * on it or use '+' to add two of them.
 *
 * The `preview*` helpers compute an indicative line total and roll-up on the
 * client so the tables show live subtotals as the user types, before a save
 * round-trips. They mirror the backend Decimal formula (time-related =
 * rate_per_period * periods; fixed = fixed_amount, each rounded to the cent, then
 * summed) so the saved figures agree with the preview. The backend summary
 * endpoint remains the authoritative source.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { toNum } from '@/shared/lib/money';

const BASE = '/v1/preliminaries';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type PrelimItemType = 'time_related' | 'fixed';

/** The grouping buckets the estimator ships (a project may add its own). */
export const PRELIM_CATEGORIES = [
  'site_establishment',
  'site_staff',
  'temporary_works',
  'standing_plant',
  'welfare',
  'general',
] as const;

/** A preliminaries item. Money fields are Decimal-as-string. */
export interface PrelimItem {
  id: string;
  project_id: string;
  label: string;
  category: string;
  item_type: PrelimItemType;
  rate_per_period: string;
  periods: string;
  fixed_amount: string;
  sort_order: number;
  line_total: string;
  created_at: string;
  updated_at: string;
}

/** One category's roll-up. Every money field is a string. */
export interface PrelimCategorySummary {
  category: string;
  time_related_total: string;
  fixed_total: string;
  total: string;
  item_count: number;
}

/** Project-level roll-up: per category plus the grand total. */
export interface PreliminariesSummary {
  project_id: string;
  categories: PrelimCategorySummary[];
  time_related_total: string;
  fixed_total: string;
  grand_total: string;
  item_count: number;
}

/** A suggested item label (amounts entered by the user). */
export interface StarterChecklistItem {
  label: string;
  category: string;
  item_type: PrelimItemType;
}

export interface StarterChecklistResponse {
  items: StarterChecklistItem[];
}

/* ── Payloads ──────────────────────────────────────────────────────────── */

export interface CreatePrelimItemPayload {
  project_id: string;
  label?: string;
  category?: string;
  item_type?: PrelimItemType;
  rate_per_period?: string;
  periods?: string;
  fixed_amount?: string;
  sort_order?: number;
}

export type UpdatePrelimItemPayload = Partial<Omit<CreatePrelimItemPayload, 'project_id'>>;

/* ── Requests ──────────────────────────────────────────────────────────── */

export async function fetchPrelimItems(projectId: string): Promise<PrelimItem[]> {
  return apiGet<PrelimItem[]>(`${BASE}/items/?project_id=${encodeURIComponent(projectId)}`);
}

export async function createPrelimItem(data: CreatePrelimItemPayload): Promise<PrelimItem> {
  return apiPost<PrelimItem>(`${BASE}/items/`, data);
}

export async function updatePrelimItem(
  itemId: string,
  data: UpdatePrelimItemPayload,
): Promise<PrelimItem> {
  return apiPatch<PrelimItem>(`${BASE}/items/${itemId}/`, data);
}

export async function deletePrelimItem(itemId: string): Promise<void> {
  return apiDelete<void>(`${BASE}/items/${itemId}/`);
}

export async function fetchPreliminariesSummary(projectId: string): Promise<PreliminariesSummary> {
  return apiGet<PreliminariesSummary>(
    `${BASE}/projects/${encodeURIComponent(projectId)}/summary/`,
  );
}

export async function fetchStarterChecklist(): Promise<StarterChecklistItem[]> {
  const res = await apiGet<StarterChecklistResponse>(`${BASE}/starter-checklist/`);
  return res.items;
}

/* ── Pure preview math (client-side live totals) ───────────────────────── */

/** The subset of an item the preview math reads (from a row or a draft form). */
export interface PrelimLineLike {
  item_type?: string | null;
  rate_per_period?: string | number | null;
  periods?: string | number | null;
  fixed_amount?: string | number | null;
  category?: string | null;
}

/** Round a number to whole cents (integer), half-up for the non-negative amounts. */
function toCents(value: number): number {
  return Math.round(value * 100);
}

/**
 * Indicative line total in currency units, rounded to the cent.
 *
 * Time-related: rate_per_period * periods. Fixed: fixed_amount. Mirrors the
 * backend {@link line_total}; the persisted figure is authoritative.
 */
export function previewLineTotal(item: PrelimLineLike): number {
  if ((item.item_type ?? 'time_related') === 'fixed') {
    return toCents(toNum(item.fixed_amount)) / 100;
  }
  return toCents(toNum(item.rate_per_period) * toNum(item.periods)) / 100;
}

export interface PreviewCategoryTotal {
  category: string;
  timeRelatedTotal: number;
  fixedTotal: number;
  total: number;
  itemCount: number;
}

export interface PreviewRollup {
  categories: PreviewCategoryTotal[];
  timeRelatedTotal: number;
  fixedTotal: number;
  grandTotal: number;
  itemCount: number;
}

/**
 * Roll a set of items up per category and in total, entirely on the client.
 *
 * Each line is rounded to the cent first (matching the backend), then summed in
 * integer cents so the grand total never drifts. Categories are sorted by label.
 */
export function previewRollup(items: PrelimLineLike[]): PreviewRollup {
  const timeByCat = new Map<string, number>();
  const fixedByCat = new Map<string, number>();
  const countByCat = new Map<string, number>();
  let grandTimeCents = 0;
  let grandFixedCents = 0;

  for (const item of items) {
    const category = (item.category ?? '').trim() || 'general';
    const cents = toCents(previewLineTotal(item));
    countByCat.set(category, (countByCat.get(category) ?? 0) + 1);
    if ((item.item_type ?? 'time_related') === 'fixed') {
      fixedByCat.set(category, (fixedByCat.get(category) ?? 0) + cents);
      grandFixedCents += cents;
    } else {
      timeByCat.set(category, (timeByCat.get(category) ?? 0) + cents);
      grandTimeCents += cents;
    }
  }

  const categories: PreviewCategoryTotal[] = [...countByCat.keys()]
    .sort((a, b) => a.localeCompare(b))
    .map((category) => {
      const timeCents = timeByCat.get(category) ?? 0;
      const fixedCents = fixedByCat.get(category) ?? 0;
      return {
        category,
        timeRelatedTotal: timeCents / 100,
        fixedTotal: fixedCents / 100,
        total: (timeCents + fixedCents) / 100,
        itemCount: countByCat.get(category) ?? 0,
      };
    });

  return {
    categories,
    timeRelatedTotal: grandTimeCents / 100,
    fixedTotal: grandFixedCents / 100,
    grandTotal: (grandTimeCents + grandFixedCents) / 100,
    itemCount: items.length,
  };
}
