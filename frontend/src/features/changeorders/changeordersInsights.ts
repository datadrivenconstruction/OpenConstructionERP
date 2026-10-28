// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Change Orders' contribution to the Module Insights panel: it turns the
 * change orders the page already loaded into one dataset plus a set of
 * built-in KPIs and charts (cost impact by reason, orders by status, register
 * growth over time, total committed value). The panel stays empty until the
 * project holds change orders.
 *
 * Labels reuse the same `changeorders.status_*` and `changeorders.reason_*`
 * i18n keys the register table and badges use, so a slice in a chart reads
 * exactly like the badge on the row it came from.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from a change order. The page's normalised
 * `ChangeOrder` type structurally satisfies this (the money field stays
 * `number | string` so the raw record is assignable without a cast).
 */
interface ChangeOrderLite {
  code?: string;
  title?: string;
  status?: string;
  reason_category?: string;
  cost_impact?: number | string;
  schedule_impact_days?: number;
  item_count?: number;
  currency?: string;
  created_at?: string;
}

// Statuses the backend workflow treats as a committed / carried-out change.
const APPROVED_STATUSES = ['approved', 'executed'];
// Still moving through the workflow, not yet decided.
const PENDING_STATUSES = ['draft', 'submitted'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'n/a';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Fallback for an unknown code: "design_change" -> "Design change". */
function humanize(code: string): string {
  const spaced = code.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced;
}

/** Reuse the register's own `changeorders.status_*` keys so a chart slice
 *  reads exactly like the status badge on the row it came from. */
function statusLabel(code: string, t: Translate): string {
  return t(`changeorders.status_${code}`, { defaultValue: humanize(code) });
}

/** Reuse the register's own `changeorders.reason_*` keys. */
function reasonLabel(code: string, t: Translate): string {
  return t(`changeorders.reason_${code}`, { defaultValue: humanize(code) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  code: string;
  title: string;
  status: string;
  reason: string;
  month: string;
  value: number;
  schedule: number;
  items: number;
  approved: number;
  pending: number;
  rejected: number;
}

function toRow(co: ChangeOrderLite, t: Translate): Row {
  const status = co.status ?? '';
  return {
    code: co.code ?? '',
    title: co.title ?? '',
    status: statusLabel(status, t),
    reason: reasonLabel(co.reason_category ?? 'client_request', t),
    month: monthKey(co.created_at ?? ''),
    value: Number(co.cost_impact) || 0,
    schedule: Number(co.schedule_impact_days) || 0,
    items: Number(co.item_count) || 0,
    approved: APPROVED_STATUSES.includes(status) ? 1 : 0,
    pending: PENDING_STATUSES.includes(status) ? 1 : 0,
    rejected: status === 'rejected' ? 1 : 0,
  };
}

export interface ChangeordersInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildChangeordersInsights(
  orders: ChangeOrderLite[],
  currency: string,
  t: Translate,
): ChangeordersInsights {
  const dateOf = (o: ChangeOrderLite): number => new Date(o.created_at ?? '').getTime();

  const rows: Row[] = [...orders]
    .sort((a, b) => (dateOf(a) || 0) - (dateOf(b) || 0))
    .map((o) => toRow(o, t));

  const dataset: InsightDataset = {
    id: 'changeorders',
    label: t('changeorders.insights.ds_orders', { defaultValue: 'Change orders' }),
    currency: currency || '',
    fields: [
      { key: 'code', label: t('changeorders.insights.f_code', { defaultValue: 'Change order' }), kind: 'dimension' },
      { key: 'status', label: t('changeorders.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'reason', label: t('changeorders.insights.f_reason', { defaultValue: 'Reason' }), kind: 'dimension' },
      { key: 'month', label: t('changeorders.insights.f_month', { defaultValue: 'Month raised' }), kind: 'dimension' },
      { key: 'value', label: t('changeorders.insights.f_value', { defaultValue: 'Cost impact' }), kind: 'measure', format: 'currency' },
      { key: 'schedule', label: t('changeorders.insights.f_schedule', { defaultValue: 'Schedule impact (days)' }), kind: 'measure', format: 'number' },
      { key: 'items', label: t('changeorders.insights.f_items', { defaultValue: 'Line items' }), kind: 'measure', format: 'number' },
      { key: 'approved', label: t('changeorders.insights.f_approved', { defaultValue: 'Approved' }), kind: 'measure', format: 'number' },
      { key: 'pending', label: t('changeorders.insights.f_pending', { defaultValue: 'Pending' }), kind: 'measure', format: 'number' },
      { key: 'rejected', label: t('changeorders.insights.f_rejected', { defaultValue: 'Rejected' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'changeorders', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-orders', title: t('changeorders.insights.k_orders', { defaultValue: 'Change orders' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-value', title: t('changeorders.insights.k_value', { defaultValue: 'Total cost impact' }), chart: 'kpi', measure: 'value', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-approved', title: t('changeorders.insights.k_approved', { defaultValue: 'Approved' }), chart: 'kpi', measure: 'approved', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-pending', title: t('changeorders.insights.k_pending', { defaultValue: 'Pending' }), chart: 'kpi', measure: 'pending', agg: 'sum', color: 4 },
    { ...base, id: 'bar-value-by-reason', title: t('changeorders.insights.c_value_by_reason', { defaultValue: 'Cost impact by reason' }), chart: 'bar', dimension: 'reason', measure: 'value', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-status', title: t('changeorders.insights.c_by_status', { defaultValue: 'Change orders by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-reason', title: t('changeorders.insights.c_by_reason', { defaultValue: 'Change orders by reason' }), chart: 'bar', dimension: 'reason', agg: 'count', color: 0 },
    { ...base, id: 'area-over-time', title: t('changeorders.insights.c_over_time', { defaultValue: 'Change orders over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
