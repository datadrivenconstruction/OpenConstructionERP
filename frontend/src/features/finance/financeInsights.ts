// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Finance's contribution to the Module Insights panel. It reads the invoices
 * the page already loaded (the register that carries every payable and
 * receivable amount, its lifecycle status and its due date) and turns them
 * into one dataset plus built-in KPIs and charts: total invoiced value, paid
 * and overdue counts, amount by counterparty, the status split and how the
 * invoiced value builds up over time. When a project has no invoices yet, the
 * panel simply stays empty until the module holds records.
 *
 * The panel charts invoices specifically (not budgets or payments): invoices
 * are where the money owed and owed-to-us lives together with a status the
 * table already colours, so a chart slice reads exactly like the badge on the
 * row it came from. Labels reuse the same `finance.status_*` and
 * `finance.payable` / `finance.receivable` i18n keys the invoice table uses.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from an invoice. The page's normalised
 * `Invoice` type structurally satisfies this (the money field stays
 * `number | string` so the raw record is assignable without a cast).
 */
interface InvoiceLite {
  invoice_number?: string;
  direction?: string;
  counterparty_name?: string;
  status?: string;
  amount?: number | string;
  currency?: string;
  issue_date?: string | null;
  invoice_date?: string | null;
  due_date?: string | null;
  created_at?: string;
}

// Statuses that mean the invoice is settled or dropped, so it is neither
// outstanding nor (for the settled case) chaseable as overdue.
const SETTLED_STATUSES = ['paid', 'cancelled'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Fallback for an unknown code: "under_review" -> "Under review". */
function humanize(code: string): string {
  const spaced = code.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced;
}

// True when an invoice's due date has passed and it is still open (not paid,
// not cancelled). Empty/invalid dates never count as overdue.
function isOverdue(dueDate: string, status: string): boolean {
  if (!dueDate || SETTLED_STATUSES.includes(status)) return false;
  const d = new Date(dueDate);
  if (Number.isNaN(d.getTime())) return false;
  return d.getTime() < Date.now();
}

// Human labels for the invoice status enum, kept as the t() defaultValue so
// English reads well before the locale keys land; an unknown code degrades
// gracefully via humanize().
const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  pending: 'Pending',
  approved: 'Approved',
  paid: 'Paid',
  disputed: 'Disputed',
  cancelled: 'Cancelled',
};

/** Reuse the invoice table's own `finance.status_*` keys so a chart slice
 *  reads exactly like the status badge on the row it came from. */
function statusLabel(code: string, t: Translate): string {
  return t(`finance.status_${code}`, { defaultValue: STATUS_LABELS[code] ?? humanize(code) });
}

/** Reuse the invoice table's `finance.payable` / `finance.receivable` keys. */
function directionLabel(code: string, t: Translate): string {
  if (code === 'receivable') return t('finance.receivable', { defaultValue: 'Receivable' });
  if (code === 'payable') return t('finance.payable', { defaultValue: 'Payable' });
  return humanize(code);
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  number: string;
  type: string;
  counterparty: string;
  status: string;
  month: string;
  amount: number;
  paid: number;
  overdue: number;
  outstanding: number;
}

function toRow(inv: InvoiceLite, unassigned: string, t: Translate): Row {
  const status = inv.status ?? '';
  const dueDate = inv.due_date ?? '';
  const dateStr = inv.issue_date ?? inv.invoice_date ?? inv.created_at ?? '';
  return {
    number: inv.invoice_number ?? '',
    type: directionLabel(inv.direction ?? 'payable', t),
    counterparty: inv.counterparty_name?.trim() || unassigned,
    status: statusLabel(status, t),
    month: monthKey(dateStr),
    amount: Number(inv.amount) || 0,
    paid: status === 'paid' ? 1 : 0,
    overdue: isOverdue(dueDate, status) ? 1 : 0,
    outstanding: SETTLED_STATUSES.includes(status) ? 0 : 1,
  };
}

export interface FinanceInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildFinanceInsights(
  invoices: InvoiceLite[],
  currency: string,
  t: Translate,
): FinanceInsights {
  const unassigned = t('finance.insights.unassigned', { defaultValue: 'Unassigned' });

  const dateOf = (i: InvoiceLite): number =>
    new Date(i.issue_date ?? i.invoice_date ?? i.created_at ?? '').getTime();

  const rows: Row[] = [...invoices]
    .sort((a, b) => (dateOf(a) || 0) - (dateOf(b) || 0))
    .map((r) => toRow(r, unassigned, t));

  const dataset: InsightDataset = {
    id: 'invoices',
    label: t('finance.insights.ds_invoices', { defaultValue: 'Invoices' }),
    currency: currency || '',
    fields: [
      { key: 'number', label: t('finance.insights.f_number', { defaultValue: 'Invoice' }), kind: 'dimension' },
      { key: 'type', label: t('finance.insights.f_type', { defaultValue: 'Direction' }), kind: 'dimension' },
      { key: 'counterparty', label: t('finance.insights.f_counterparty', { defaultValue: 'Counterparty' }), kind: 'dimension' },
      { key: 'status', label: t('finance.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'month', label: t('finance.insights.f_month', { defaultValue: 'Month' }), kind: 'dimension' },
      { key: 'amount', label: t('finance.insights.f_amount', { defaultValue: 'Amount' }), kind: 'measure', format: 'currency' },
      { key: 'paid', label: t('finance.insights.f_paid', { defaultValue: 'Paid' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('finance.insights.f_overdue', { defaultValue: 'Overdue' }), kind: 'measure', format: 'number' },
      { key: 'outstanding', label: t('finance.insights.f_outstanding', { defaultValue: 'Outstanding' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'invoices', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-count', title: t('finance.insights.k_count', { defaultValue: 'Invoices' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-value', title: t('finance.insights.k_value', { defaultValue: 'Total invoiced' }), chart: 'kpi', measure: 'amount', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-paid', title: t('finance.insights.k_paid', { defaultValue: 'Paid' }), chart: 'kpi', measure: 'paid', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-overdue', title: t('finance.insights.k_overdue', { defaultValue: 'Overdue' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 4 },
    { ...base, id: 'bar-amount-by-counterparty', title: t('finance.insights.c_amount_by_counterparty', { defaultValue: 'Amount by counterparty' }), chart: 'bar', dimension: 'counterparty', measure: 'amount', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-status', title: t('finance.insights.c_by_status', { defaultValue: 'Invoices by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-type', title: t('finance.insights.c_by_type', { defaultValue: 'Invoices by direction' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'area-over-time', title: t('finance.insights.c_over_time', { defaultValue: 'Invoiced over time' }), chart: 'area', dimension: 'month', measure: 'amount', agg: 'sum', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
