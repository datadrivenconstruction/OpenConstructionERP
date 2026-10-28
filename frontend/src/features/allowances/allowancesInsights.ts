// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Allowances register's contribution to the Module Insights panel: it turns the
 * allowances the page already loaded (provisional sums, prime-cost sums and
 * contingencies, each holding an amount that is drawn down as scope firms up)
 * into one dataset plus built-in KPIs and charts: total held and remaining, how
 * many are over-drawn, held by type, the status split and how the register
 * builds up over time. The panel stays empty until the register holds
 * allowance records.
 *
 * Slice labels reuse the same `allowances.type_*` keys the register table uses
 * (via allowanceTypeLabelKey) and the `allowances.overdrawn` badge key, so a
 * slice in a chart reads exactly like the row it came from.
 */
import { useTranslation } from 'react-i18next';
import { toNum } from '@/shared/lib/money';
import type { InsightDataset, InsightDef } from '@/features/insights';
import { allowanceTypeLabelKey, ALLOWANCE_TYPE_DEFAULT_LABELS, type AllowanceType } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from an allowance. The page's `Allowance`
 * type structurally satisfies this (money fields stay `number | string` so the
 * raw record is assignable without a cast).
 */
interface AllowanceLite {
  label?: string;
  allowance_type?: string;
  held_amount?: number | string;
  drawn?: number | string;
  remaining?: number | string;
  overdrawn?: boolean;
  currency?: string;
  created_at?: string;
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Fallback for an unknown code: "pc_sum" -> "Pc sum". */
function humanize(code: string): string {
  const spaced = code.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced;
}

/** Reuse the register's own `allowances.type_*` keys so a chart slice reads
 *  exactly like the type heading on the rows it came from. */
function typeLabel(code: string, t: Translate): string {
  return t(allowanceTypeLabelKey(code), {
    defaultValue: ALLOWANCE_TYPE_DEFAULT_LABELS[code as AllowanceType] ?? humanize(code),
  });
}

/** Over-drawn reuses the table's `allowances.overdrawn` badge; the healthy case
 *  gets its own insights label. */
function statusLabel(overdrawn: boolean, t: Translate): string {
  return overdrawn
    ? t('allowances.overdrawn', { defaultValue: 'Over-drawn' })
    : t('allowances.insights.status_within', { defaultValue: 'Within allowance' });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  label: string;
  type: string;
  status: string;
  month: string;
  held: number;
  drawn: number;
  remaining: number;
  overdrawn: number;
}

function toRow(a: AllowanceLite, t: Translate): Row {
  const over = a.overdrawn === true;
  return {
    label: a.label ?? '',
    type: typeLabel(a.allowance_type ?? 'provisional_sum', t),
    status: statusLabel(over, t),
    month: monthKey(a.created_at ?? ''),
    held: toNum(a.held_amount),
    drawn: toNum(a.drawn),
    remaining: toNum(a.remaining),
    overdrawn: over ? 1 : 0,
  };
}

export interface AllowancesInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildAllowancesInsights(
  allowances: AllowanceLite[],
  currency: string,
  t: Translate,
): AllowancesInsights {
  const dateOf = (a: AllowanceLite): number => new Date(a.created_at ?? '').getTime();

  const rows: Row[] = [...allowances]
    .sort((a, b) => (dateOf(a) || 0) - (dateOf(b) || 0))
    .map((a) => toRow(a, t));

  const dataset: InsightDataset = {
    id: 'allowances',
    label: t('allowances.insights.ds_allowances', { defaultValue: 'Allowances register' }),
    currency: currency || '',
    fields: [
      { key: 'label', label: t('allowances.insights.f_label', { defaultValue: 'Allowance' }), kind: 'dimension' },
      { key: 'type', label: t('allowances.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('allowances.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'month', label: t('allowances.insights.f_month', { defaultValue: 'Month added' }), kind: 'dimension' },
      { key: 'held', label: t('allowances.insights.f_held', { defaultValue: 'Held' }), kind: 'measure', format: 'currency' },
      { key: 'drawn', label: t('allowances.insights.f_drawn', { defaultValue: 'Drawn down' }), kind: 'measure', format: 'currency' },
      { key: 'remaining', label: t('allowances.insights.f_remaining', { defaultValue: 'Remaining' }), kind: 'measure', format: 'currency' },
      { key: 'overdrawn', label: t('allowances.insights.f_overdrawn', { defaultValue: 'Over-drawn' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'allowances', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-count', title: t('allowances.insights.k_count', { defaultValue: 'Allowances' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-held', title: t('allowances.insights.k_held', { defaultValue: 'Total held' }), chart: 'kpi', measure: 'held', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-remaining', title: t('allowances.insights.k_remaining', { defaultValue: 'Remaining in estimate' }), chart: 'kpi', measure: 'remaining', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-overdrawn', title: t('allowances.insights.k_overdrawn', { defaultValue: 'Over-drawn' }), chart: 'kpi', measure: 'overdrawn', agg: 'sum', color: 4 },
    { ...base, id: 'bar-held-by-type', title: t('allowances.insights.c_held_by_type', { defaultValue: 'Held by type' }), chart: 'bar', dimension: 'type', measure: 'held', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-status', title: t('allowances.insights.c_by_status', { defaultValue: 'Allowances by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-drawn-by-type', title: t('allowances.insights.c_drawn_by_type', { defaultValue: 'Drawn down by type' }), chart: 'bar', dimension: 'type', measure: 'drawn', agg: 'sum', color: 0 },
    { ...base, id: 'area-over-time', title: t('allowances.insights.c_over_time', { defaultValue: 'Allowances added over time' }), chart: 'area', dimension: 'month', measure: 'held', agg: 'sum', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
