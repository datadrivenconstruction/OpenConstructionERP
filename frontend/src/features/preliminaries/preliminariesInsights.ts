// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Preliminaries estimator's contribution to the Module Insights panel: it turns
 * the preliminaries items the page already loaded (time-related and fixed
 * general-conditions items, each with a line total and a category) into one
 * dataset plus built-in KPIs and charts: the preliminaries total, how many
 * items are time-related and fixed, cost by category, the time-vs-fixed split
 * and how the cost builds up over time. When a project has no items yet, the
 * panel simply stays empty until the estimator holds records.
 *
 * Slice labels reuse the same `preliminaries.category_*` keys the tables use and
 * the `preliminaries.time_related_total` / `preliminaries.fixed_total` labels
 * the summary strip uses, so a slice in a chart reads exactly like the register
 * it came from.
 */
import { useTranslation } from 'react-i18next';
import { toNum } from '@/shared/lib/money';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from a preliminaries item. The page's
 * `PrelimItem` type structurally satisfies this (the money field stays
 * `number | string` so the raw record is assignable without a cast).
 */
interface PrelimItemLite {
  label?: string;
  category?: string | null;
  item_type?: string | null;
  line_total?: number | string | null;
  created_at?: string;
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Fallback for an unknown code: "site_staff" -> "Site staff". */
function humanize(code: string): string {
  const spaced = code.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced;
}

/** Reuse the tables' own `preliminaries.category_*` keys so a chart slice reads
 *  exactly like the category cell on the row it came from. */
function categoryLabel(code: string, t: Translate): string {
  return t(`preliminaries.category_${code}`, { defaultValue: humanize(code) });
}

/** Reuse the summary strip's time-related / fixed labels for the type split. */
function typeLabel(isFixed: boolean, t: Translate): string {
  return isFixed
    ? t('preliminaries.fixed_total', { defaultValue: 'Fixed one-off' })
    : t('preliminaries.time_related_total', { defaultValue: 'Time-related' });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  label: string;
  category: string;
  type: string;
  month: string;
  amount: number;
  time_related: number;
  fixed: number;
}

function toRow(item: PrelimItemLite, t: Translate): Row {
  const isFixed = (item.item_type ?? 'time_related') === 'fixed';
  return {
    label: item.label ?? '',
    category: categoryLabel(item.category || 'general', t),
    type: typeLabel(isFixed, t),
    month: monthKey(item.created_at ?? ''),
    amount: toNum(item.line_total),
    time_related: isFixed ? 0 : 1,
    fixed: isFixed ? 1 : 0,
  };
}

export interface PreliminariesInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildPreliminariesInsights(
  items: PrelimItemLite[],
  currency: string,
  t: Translate,
): PreliminariesInsights {
  const dateOf = (i: PrelimItemLite): number => new Date(i.created_at ?? '').getTime();

  const rows: Row[] = [...items].sort((a, b) => (dateOf(a) || 0) - (dateOf(b) || 0)).map((i) => toRow(i, t));

  const dataset: InsightDataset = {
    id: 'preliminaries',
    label: t('preliminaries.insights.ds_items', { defaultValue: 'Preliminaries' }),
    currency: currency || '',
    fields: [
      { key: 'label', label: t('preliminaries.insights.f_label', { defaultValue: 'Item' }), kind: 'dimension' },
      { key: 'category', label: t('preliminaries.insights.f_category', { defaultValue: 'Category' }), kind: 'dimension' },
      { key: 'type', label: t('preliminaries.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'month', label: t('preliminaries.insights.f_month', { defaultValue: 'Month added' }), kind: 'dimension' },
      { key: 'amount', label: t('preliminaries.insights.f_amount', { defaultValue: 'Line total' }), kind: 'measure', format: 'currency' },
      { key: 'time_related', label: t('preliminaries.insights.f_time_related', { defaultValue: 'Time-related' }), kind: 'measure', format: 'number' },
      { key: 'fixed', label: t('preliminaries.insights.f_fixed', { defaultValue: 'Fixed' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'preliminaries', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-count', title: t('preliminaries.insights.k_count', { defaultValue: 'Items' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-total', title: t('preliminaries.insights.k_total', { defaultValue: 'Preliminaries total' }), chart: 'kpi', measure: 'amount', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-time', title: t('preliminaries.insights.k_time', { defaultValue: 'Time-related items' }), chart: 'kpi', measure: 'time_related', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-fixed', title: t('preliminaries.insights.k_fixed', { defaultValue: 'Fixed items' }), chart: 'kpi', measure: 'fixed', agg: 'sum', color: 4 },
    { ...base, id: 'bar-cost-by-category', title: t('preliminaries.insights.c_cost_by_category', { defaultValue: 'Cost by category' }), chart: 'bar', dimension: 'category', measure: 'amount', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-type', title: t('preliminaries.insights.c_by_type', { defaultValue: 'Items by type' }), chart: 'donut', dimension: 'type', agg: 'count', color: 4 },
    { ...base, id: 'bar-cost-by-type', title: t('preliminaries.insights.c_cost_by_type', { defaultValue: 'Cost by type' }), chart: 'bar', dimension: 'type', measure: 'amount', agg: 'sum', color: 0 },
    { ...base, id: 'area-over-time', title: t('preliminaries.insights.c_over_time', { defaultValue: 'Cost added over time' }), chart: 'area', dimension: 'month', measure: 'amount', agg: 'sum', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
