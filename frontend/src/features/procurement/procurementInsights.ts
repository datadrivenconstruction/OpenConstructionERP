// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Procurement's contribution to the Module Insights panel. It reads the
 * purchase orders the page already loaded (the register that carries the
 * committed value of every order, its supplier and its delivery status) and
 * turns them into one dataset plus built-in KPIs and charts: total committed
 * value, open vs received counts, value by supplier, the status split and how
 * the committed value builds up over time. When a project has no orders yet,
 * the panel simply stays empty until the register holds records.
 *
 * The panel charts purchase orders specifically (not requisitions): orders are
 * where the committed spend and the delivery status live together, so a chart
 * slice reads exactly like the status badge on the row it came from. Status
 * labels reuse the same `procurement.po_status_*` i18n keys the order table
 * uses.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from a purchase order. The page's real
 * `PurchaseOrder` type structurally satisfies this (the money field stays
 * `number | string` so the raw record is assignable without a cast).
 */
interface PurchaseOrderLite {
  po_number?: string;
  vendor_name?: string;
  status?: string;
  amount_total?: number | string;
  currency_code?: string;
  issue_date?: string;
  created_at?: string;
}

// An order counts as received once fully or partially handed over into stock,
// and stays "open" until it is received, completed, cancelled or closed.
const RECEIVED_STATUSES = ['received', 'completed'];
const CLOSED_STATUSES = ['received', 'completed', 'cancelled', 'closed'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Fallback for an unknown code: "partially_received" -> "Partially received". */
function humanize(code: string): string {
  const spaced = code.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced;
}

// Human labels for the purchase-order status enum, kept as the t() default so
// English reads well before the locale keys land; an unknown code degrades
// gracefully via humanize().
const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  pending: 'Pending',
  approved: 'Approved',
  issued: 'Issued',
  partial: 'Partially received',
  received: 'Received',
  completed: 'Completed',
  cancelled: 'Cancelled',
  closed: 'Closed',
};

/** Reuse the order table's own `procurement.po_status_*` keys so a chart slice
 *  reads exactly like the status badge on the row it came from. */
function statusLabel(code: string, t: Translate): string {
  return t(`procurement.po_status_${code}`, { defaultValue: STATUS_LABELS[code] ?? humanize(code) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  number: string;
  supplier: string;
  status: string;
  month: string;
  value: number;
  open: number;
  received: number;
}

function toRow(po: PurchaseOrderLite, unassigned: string, t: Translate): Row {
  const status = po.status ?? '';
  return {
    number: po.po_number ?? '',
    supplier: po.vendor_name?.trim() || unassigned,
    status: statusLabel(status, t),
    month: monthKey(po.issue_date ?? po.created_at ?? ''),
    value: Number(po.amount_total) || 0,
    open: CLOSED_STATUSES.includes(status) ? 0 : 1,
    received: RECEIVED_STATUSES.includes(status) ? 1 : 0,
  };
}

export interface ProcurementInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildProcurementInsights(
  orders: PurchaseOrderLite[],
  currency: string,
  t: Translate,
): ProcurementInsights {
  const unassigned = t('procurement.insights.unassigned', { defaultValue: 'Unassigned' });

  const dateOf = (o: PurchaseOrderLite): number =>
    new Date(o.issue_date ?? o.created_at ?? '').getTime();

  const rows: Row[] = [...orders]
    .sort((a, b) => (dateOf(a) || 0) - (dateOf(b) || 0))
    .map((o) => toRow(o, unassigned, t));

  const dataset: InsightDataset = {
    id: 'purchase_orders',
    label: t('procurement.insights.ds_orders', { defaultValue: 'Purchase orders' }),
    currency: currency || '',
    fields: [
      { key: 'number', label: t('procurement.insights.f_number', { defaultValue: 'PO' }), kind: 'dimension' },
      { key: 'supplier', label: t('procurement.insights.f_supplier', { defaultValue: 'Supplier' }), kind: 'dimension' },
      { key: 'status', label: t('procurement.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'month', label: t('procurement.insights.f_month', { defaultValue: 'Month' }), kind: 'dimension' },
      { key: 'value', label: t('procurement.insights.f_value', { defaultValue: 'Order value' }), kind: 'measure', format: 'currency' },
      { key: 'open', label: t('procurement.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'received', label: t('procurement.insights.f_received', { defaultValue: 'Received' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'purchase_orders', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-count', title: t('procurement.insights.k_count', { defaultValue: 'Purchase orders' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-value', title: t('procurement.insights.k_value', { defaultValue: 'Total PO value' }), chart: 'kpi', measure: 'value', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-open', title: t('procurement.insights.k_open', { defaultValue: 'Open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-received', title: t('procurement.insights.k_received', { defaultValue: 'Received' }), chart: 'kpi', measure: 'received', agg: 'sum', color: 4 },
    { ...base, id: 'bar-value-by-supplier', title: t('procurement.insights.c_value_by_supplier', { defaultValue: 'Value by supplier' }), chart: 'bar', dimension: 'supplier', measure: 'value', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-status', title: t('procurement.insights.c_by_status', { defaultValue: 'Orders by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-value-by-status', title: t('procurement.insights.c_value_by_status', { defaultValue: 'Value by status' }), chart: 'bar', dimension: 'status', measure: 'value', agg: 'sum', color: 0 },
    { ...base, id: 'area-over-time', title: t('procurement.insights.c_over_time', { defaultValue: 'Committed value over time' }), chart: 'area', dimension: 'month', measure: 'value', agg: 'sum', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
