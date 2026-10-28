// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Resources' contribution to the Module Insights panel: it turns the resource
 * register the page already loaded into one dataset plus a set of built-in KPIs
 * and charts (resources by type and status, average cost rate, register growth
 * over time). When there are no resources yet, the panel simply stays empty
 * until the register holds records.
 *
 * The record carries one real money field, the default cost rate, so the rate
 * measure formats as currency; the active / on-leave measures are plain counts.
 * Type and status slices reuse the same `resources.type_*` / `resources.status_*`
 * keys the register table uses, so a chart slice reads exactly like the badge on
 * the row it came from.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from a resource. The page's real `Resource`
 * type structurally satisfies this (its type / status unions are assignable to
 * `string`, and money stays `number | string`) so the raw record is assignable
 * without a cast.
 */
interface ResourceLite {
  name: string;
  resource_type: string;
  status: string;
  default_cost_rate: number | string;
  created_at: string;
}

/** English fallbacks matching the register's own type labels. */
const TYPE_LABELS: Record<string, string> = {
  person: 'Person',
  crew: 'Crew',
  equipment: 'Equipment',
  subcontractor: 'Subcontractor',
};

/** English fallbacks matching the register's own status labels. */
const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  on_leave: 'On leave',
  inactive: 'Inactive',
};

/** Coerce a decimal-as-string cell to a finite number (0 when absent/invalid). */
function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Fallback for an unknown code: "on_leave" -> "On leave". */
function humanize(code: string): string {
  const spaced = code.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced;
}

/** Reuse the register's `resources.type_*` keys so a slice matches the table. */
function typeLabel(code: string, t: Translate): string {
  return t(`resources.type_${code}`, { defaultValue: TYPE_LABELS[code] ?? humanize(code) });
}

/** Reuse the register's `resources.status_*` keys so a slice matches the table. */
function statusLabel(code: string, t: Translate): string {
  return t(`resources.status_${code}`, { defaultValue: STATUS_LABELS[code] ?? humanize(code) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  name: string;
  type: string;
  status: string;
  month: string;
  rate: number;
  active: number;
  on_leave: number;
}

function toRow(r: ResourceLite, t: Translate): Row {
  return {
    name: r.name ?? '',
    type: typeLabel(r.resource_type, t),
    status: statusLabel(r.status, t),
    month: monthKey(r.created_at),
    rate: toNum(r.default_cost_rate),
    active: r.status === 'active' ? 1 : 0,
    on_leave: r.status === 'on_leave' ? 1 : 0,
  };
}

export interface ResourcesInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildResourcesInsights(
  resources: ResourceLite[],
  currency: string,
  t: Translate,
): ResourcesInsights {
  const rows: Row[] = [...resources]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'resources',
    label: t('resources.insights.ds_resources', { defaultValue: 'Resource register' }),
    currency: currency || '',
    fields: [
      { key: 'name', label: t('resources.insights.f_name', { defaultValue: 'Name' }), kind: 'dimension' },
      { key: 'type', label: t('resources.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('resources.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'month', label: t('resources.insights.f_month', { defaultValue: 'Added' }), kind: 'dimension' },
      { key: 'rate', label: t('resources.insights.f_rate', { defaultValue: 'Cost rate' }), kind: 'measure', format: 'currency' },
      { key: 'active', label: t('resources.insights.f_active', { defaultValue: 'Active' }), kind: 'measure', format: 'number' },
      { key: 'on_leave', label: t('resources.insights.f_on_leave', { defaultValue: 'On leave' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'resources', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-resources', title: t('resources.insights.k_resources', { defaultValue: 'Resources' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-active', title: t('resources.insights.k_active', { defaultValue: 'Active' }), chart: 'kpi', measure: 'active', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-on-leave', title: t('resources.insights.k_on_leave', { defaultValue: 'On leave' }), chart: 'kpi', measure: 'on_leave', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-avg-rate', title: t('resources.insights.k_avg_rate', { defaultValue: 'Avg cost rate' }), chart: 'kpi', measure: 'rate', agg: 'avg', color: 4 },
    { ...base, id: 'bar-by-type', title: t('resources.insights.c_by_type', { defaultValue: 'Resources by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('resources.insights.c_by_status', { defaultValue: 'Resources by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-rate-by-type', title: t('resources.insights.c_rate_by_type', { defaultValue: 'Avg rate by type' }), chart: 'bar', dimension: 'type', measure: 'rate', agg: 'avg', color: 2 },
    { ...base, id: 'area-over-time', title: t('resources.insights.c_over_time', { defaultValue: 'Resources added over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
