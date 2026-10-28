// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Quality module's contribution to the Module Insights panel. It charts the
 * punch list - the register a quality lead lives in day to day - turning the
 * punch items the page loaded into one dataset plus built-in KPIs and charts:
 * how many items are open, how many are overdue, how long they take to close,
 * which trades they land on and how the list grows over time. When a project
 * has no punch items yet, the panel simply stays empty until the register
 * holds records.
 *
 * Labels reuse the same `qms.category_label.*` / `qms.severity_level.*` /
 * `qms.status.*` i18n keys the punch table uses, so a slice in a chart reads
 * exactly like the badge on the row it came from. Only fields that genuinely
 * exist on a punch item are charted, and the "average days to close" KPI
 * averages over closed items alone - open items carry a blank close-time cell
 * that the aggregator skips, so the figure is never diluted by unfinished work.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import { parseDateUTC } from '@/shared/lib/dates';

type Translate = ReturnType<typeof useTranslation>['t'];

/** Minimal shape the builder needs; a real PunchItem row satisfies it. */
interface PunchLite {
  title: string;
  category: string | null;
  severity: string;
  status: string;
  raised_at: string | null;
  due_date: string | null;
  closed_at: string | null;
}

// Statuses that are no longer live work - a rejected item is dispositioned, a
// closed item is fixed, so neither counts as open (enum:
// open|assigned|in_progress|ready_for_inspection|closed|rejected).
const CLOSED_STATUSES = ['closed', 'rejected'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Humanised fallback for a snake_case enum token (e.g. ready_for_inspection -> Ready for inspection). */
function humanize(code: string): string {
  const s = code.replace(/_/g, ' ').trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : '—';
}

function categoryLabel(code: string | null, t: Translate): string {
  if (!code) return ''; // an unfiled item falls into the aggregator's blank group
  return t(`qms.category_label.${code}`, { defaultValue: humanize(code) });
}

function severityLabel(code: string, t: Translate): string {
  return t(`qms.severity_level.${code}`, { defaultValue: humanize(code) });
}

function statusLabel(code: string, t: Translate): string {
  return t(`qms.status.${code}`, { defaultValue: humanize(code) });
}

/** Days from raised to closed for a resolved item; '' (skipped by avg) otherwise. */
function closeDays(r: PunchLite): number | '' {
  if (!r.closed_at || !r.raised_at) return '';
  const raised = new Date(r.raised_at).getTime();
  const closed = new Date(r.closed_at).getTime();
  if (Number.isNaN(raised) || Number.isNaN(closed) || closed < raised) return '';
  return Math.round((closed - raised) / 86_400_000);
}

/** An item is overdue when its due date has passed and it is still live work. */
function isOverdue(r: PunchLite, now: number): number {
  if (!r.due_date || CLOSED_STATUSES.includes(r.status)) return 0;
  const due = parseDateUTC(r.due_date).getTime();
  return !Number.isNaN(due) && due < now ? 1 : 0;
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  category: string;
  severity: string;
  status: string;
  month: string;
  open: number;
  overdue: number;
  close_days: number | '';
}

function toRow(r: PunchLite, t: Translate, now: number): Row {
  return {
    title: r.title ?? '',
    category: categoryLabel(r.category, t),
    severity: severityLabel(r.severity, t),
    status: statusLabel(r.status, t),
    month: monthKey(r.raised_at ?? ''),
    open: CLOSED_STATUSES.includes(r.status) ? 0 : 1,
    overdue: isOverdue(r, now),
    close_days: closeDays(r),
  };
}

export interface QMSInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildQMSInsights(
  punchItems: PunchLite[],
  currency: string,
  t: Translate,
): QMSInsights {
  const now = Date.now();

  const rows: Row[] = [...punchItems]
    .sort((a, b) => new Date(a.raised_at ?? '').getTime() - new Date(b.raised_at ?? '').getTime())
    .map((r) => toRow(r, t, now));

  const dataset: InsightDataset = {
    id: 'punch',
    label: t('qms.insights.ds_punch', { defaultValue: 'Punch list' }),
    // Punch items carry no money field, so no currency measure is charted; the
    // parameter is kept for template parity with the other module builders.
    currency: currency || '',
    fields: [
      { key: 'title', label: t('qms.insights.f_title', { defaultValue: 'Item' }), kind: 'dimension' },
      { key: 'category', label: t('qms.insights.f_category', { defaultValue: 'Category' }), kind: 'dimension' },
      { key: 'severity', label: t('qms.insights.f_severity', { defaultValue: 'Severity' }), kind: 'dimension' },
      { key: 'status', label: t('qms.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'month', label: t('qms.insights.f_month', { defaultValue: 'Month raised' }), kind: 'dimension' },
      { key: 'open', label: t('qms.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('qms.insights.f_overdue', { defaultValue: 'Overdue' }), kind: 'measure', format: 'number' },
      { key: 'close_days', label: t('qms.insights.f_close_days', { defaultValue: 'Days to close' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'punch', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-punch', title: t('qms.insights.k_punch', { defaultValue: 'Punch items' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('qms.insights.k_open', { defaultValue: 'Open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-overdue', title: t('qms.insights.k_overdue', { defaultValue: 'Overdue' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-close-time', title: t('qms.insights.k_close_time', { defaultValue: 'Avg days to close' }), chart: 'kpi', measure: 'close_days', agg: 'avg', color: 3 },
    { ...base, id: 'bar-by-category', title: t('qms.insights.c_by_category', { defaultValue: 'Punch items by category' }), chart: 'bar', dimension: 'category', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-severity', title: t('qms.insights.c_by_severity', { defaultValue: 'Punch items by severity' }), chart: 'donut', dimension: 'severity', agg: 'count', color: 1 },
    { ...base, id: 'bar-by-status', title: t('qms.insights.c_by_status', { defaultValue: 'Punch items by status' }), chart: 'bar', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'area-over-time', title: t('qms.insights.c_over_time', { defaultValue: 'Punch items over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
