// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Temporary works register's contribution to the Module Insights panel: it
 * turns the items the page already loaded into one dataset plus a set of built-in
 * KPIs and charts (items by type, by status, by design check category, and how
 * many are added over time). When a project has no items yet, the panel simply
 * stays empty until the register holds records.
 *
 * Value labels reuse the same `temporary_works.status_*` / `temporary_works.tw_type_*`
 * / `temporary_works.category_*` i18n keys the register table uses, so a slice in
 * a chart reads exactly like the badge on the row it came from. These are count /
 * lifecycle insights: a temporary works item carries no money field, so every
 * measure is a plain number (a count, a 0/1 flag or a day count) - there is no
 * currency KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from a temporary works item. The page hands
// it the full TemporaryWorksItem[] (structurally a superset of this), so no
// mapping is needed at the call site.
interface ItemLite {
  title: string;
  status: string;
  tw_type: string;
  design_check_category: string | null;
  twc_name: string | null;
  required_load_date: string | null;
  created_at: string;
  updated_at: string;
}

// Statuses whose item is bearing construction load right now.
const LOAD_BEARING_STATUSES = ['loaded', 'in_use'];
// struck / removed items are off the critical path; their "days on register"
// clock stops at the last update. Everything else is still live.
const DONE_STATUSES = ['struck', 'removed'];
// At or beyond the independent design check - the design clearance gate is met.
const DESIGN_CLEARED_STATUSES = [
  'design_checked',
  'approved_to_load',
  'loaded',
  'in_use',
  'approved_to_strike',
  'struck',
  'removed',
];
// Still working towards load: a past required-load date on one of these is a
// genuine "overdue to load" signal (loaded / in_use / struck / removed / on_hold
// are excluded, since they are not waiting to be loaded).
const PRE_LOAD_STATUSES = [
  'identified',
  'design_brief',
  'design_submitted',
  'design_checked',
  'approved_to_load',
];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Reasonable title-case fallback; the real translation wins when present. */
function humanize(code: string): string {
  const s = code.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function statusLabel(code: string, t: Translate): string {
  return t(`temporary_works.status_${code}`, { defaultValue: humanize(code) });
}

function typeLabel(code: string, t: Translate): string {
  return t(`temporary_works.tw_type_${code}`, { defaultValue: humanize(code) });
}

function categoryLabel(code: string | null, t: Translate): string {
  if (!code) return t('temporary_works.category_unassigned', { defaultValue: 'Unassigned' });
  return t(`temporary_works.category_${code}`, { defaultValue: `Category ${code}` });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  type: string;
  status: string;
  category: string;
  twc: string;
  month: string;
  load_bearing: number;
  design_cleared: number;
  on_hold: number;
  overdue_load: number;
  age: number;
}

/** Whole days the item has been (or was) on the register: created -> now for a
 *  live one, created -> last update for a struck / removed one. Never negative. */
function daysOnRegister(r: ItemLite): number {
  const start = new Date(r.created_at).getTime();
  if (Number.isNaN(start)) return 0;
  const done = DONE_STATUSES.includes(r.status);
  const endRaw = done ? new Date(r.updated_at).getTime() : Date.now();
  const end = Number.isNaN(endRaw) ? Date.now() : endRaw;
  return Math.max(0, Math.floor((end - start) / 86_400_000));
}

function toRow(r: ItemLite, unassigned: string, today: string, t: Translate): Row {
  const overdueLoad =
    !!r.required_load_date && r.required_load_date < today && PRE_LOAD_STATUSES.includes(r.status)
      ? 1
      : 0;
  return {
    title: r.title ?? '',
    type: typeLabel(r.tw_type, t),
    status: statusLabel(r.status, t),
    category: categoryLabel(r.design_check_category, t),
    twc: r.twc_name?.trim() || unassigned,
    month: monthKey(r.created_at),
    load_bearing: LOAD_BEARING_STATUSES.includes(r.status) ? 1 : 0,
    design_cleared: DESIGN_CLEARED_STATUSES.includes(r.status) ? 1 : 0,
    on_hold: r.status === 'on_hold' ? 1 : 0,
    overdue_load: overdueLoad,
    age: daysOnRegister(r),
  };
}

export interface TemporaryWorksInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildTemporaryWorksInsights(
  items: ItemLite[],
  currency: string,
  t: Translate,
): TemporaryWorksInsights {
  const unassigned = t('temporary_works.insights.unassigned', { defaultValue: 'Unassigned' });
  const today = new Date().toISOString().slice(0, 10);

  const rows: Row[] = [...items]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, unassigned, today, t));

  const dataset: InsightDataset = {
    id: 'items',
    label: t('temporary_works.insights.ds_items', { defaultValue: 'Temporary works register' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('temporary_works.insights.f_title', { defaultValue: 'Item' }), kind: 'dimension' },
      { key: 'type', label: t('temporary_works.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('temporary_works.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'category', label: t('temporary_works.insights.f_category', { defaultValue: 'Design check category' }), kind: 'dimension' },
      { key: 'twc', label: t('temporary_works.insights.f_twc', { defaultValue: 'Coordinator' }), kind: 'dimension' },
      { key: 'month', label: t('temporary_works.insights.f_month', { defaultValue: 'Month added' }), kind: 'dimension' },
      { key: 'load_bearing', label: t('temporary_works.insights.f_load_bearing', { defaultValue: 'Bearing load' }), kind: 'measure', format: 'number' },
      { key: 'design_cleared', label: t('temporary_works.insights.f_design_cleared', { defaultValue: 'Design cleared' }), kind: 'measure', format: 'number' },
      { key: 'on_hold', label: t('temporary_works.insights.f_on_hold', { defaultValue: 'On hold' }), kind: 'measure', format: 'number' },
      { key: 'overdue_load', label: t('temporary_works.insights.f_overdue_load', { defaultValue: 'Overdue to load' }), kind: 'measure', format: 'number' },
      { key: 'age', label: t('temporary_works.insights.f_age', { defaultValue: 'Days on register' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'items', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-items', title: t('temporary_works.insights.k_items', { defaultValue: 'Items' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-load-bearing', title: t('temporary_works.insights.k_load_bearing', { defaultValue: 'Bearing load' }), chart: 'kpi', measure: 'load_bearing', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-overdue-load', title: t('temporary_works.insights.k_overdue_load', { defaultValue: 'Overdue to load' }), chart: 'kpi', measure: 'overdue_load', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-avg-age', title: t('temporary_works.insights.k_avg_age', { defaultValue: 'Avg days on register' }), chart: 'kpi', measure: 'age', agg: 'avg', color: 3 },
    { ...base, id: 'bar-by-type', title: t('temporary_works.insights.c_by_type', { defaultValue: 'Items by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('temporary_works.insights.c_by_status', { defaultValue: 'Items by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-category', title: t('temporary_works.insights.c_by_category', { defaultValue: 'Items by design check category' }), chart: 'bar', dimension: 'category', agg: 'count', color: 5 },
    { ...base, id: 'area-over-time', title: t('temporary_works.insights.c_over_time', { defaultValue: 'Items added over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 3 },
  ];

  return { datasets: [dataset], builtins };
}
