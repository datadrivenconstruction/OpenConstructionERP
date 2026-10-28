// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Submittal register's contribution to the Module Insights panel: it turns the
 * submittals the page already loaded into one dataset plus a set of built-in
 * KPIs and charts (submittals by type, by status, who currently owes the next
 * move, and how many are raised over time). When a project has no submittals
 * yet the dataset is empty and the panel shows nothing, which is the honest
 * answer for a register nobody has filled in.
 *
 * Value labels reuse the same `submittals.status_*` / `submittals.type_*` i18n
 * keys the register table uses, so a slice in a chart reads exactly like the
 * badge on the row it came from. These are count / age / status insights: a
 * submittal carries no money field, so every measure is a plain number (a
 * count, a day count or a 0/1 flag) - there is no currency KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import { parseDateUTC } from '@/shared/lib/dates';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from a submittal. The page hands it the full
// Submittal[] (structurally a superset of this), so no mapping is needed at the
// call site.
interface SubmittalLite {
  title: string;
  status: string;
  type: string;
  spec_section: string | null;
  date_required: string | null;
  created_at: string;
  updated_at: string;
}

// A submittal is done once it is approved (with or without notes), rejected or
// closed - nobody owes the next move on it and its "days open" clock stops at
// the last update. draft / submitted / under_review / revise_and_resubmit are
// still open. There is no dedicated close date, so updated_at is the best
// available proxy for when the clock stopped.
const DONE_STATUSES = ['approved', 'approved_as_noted', 'rejected', 'closed'];
const APPROVED_STATUSES = ['approved', 'approved_as_noted'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Reasonable title-case fallback; the real translation wins when present. */
function humanize(code: string): string {
  const s = code.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Whole days the submittal has been (or was) open: created -> now for an open
 *  one, created -> last update for a done one. Never negative. */
function daysOpen(r: SubmittalLite): number {
  const start = new Date(r.created_at).getTime();
  if (Number.isNaN(start)) return 0;
  const done = DONE_STATUSES.includes(r.status);
  const endRaw = done ? new Date(r.updated_at).getTime() : Date.now();
  const end = Number.isNaN(endRaw) ? Date.now() : endRaw;
  return Math.max(0, Math.floor((end - start) / 86_400_000));
}

function statusLabel(code: string, t: Translate): string {
  return t(`submittals.status_${code}`, { defaultValue: humanize(code) });
}

function typeLabel(code: string, t: Translate): string {
  return t(`submittals.type_${code}`, { defaultValue: humanize(code) });
}

function specLabel(spec: string | null, t: Translate): string {
  const s = spec?.trim();
  return s ? s : t('submittals.insights.no_spec', { defaultValue: 'No spec section' });
}

// Ball-in-court derived from status alone, so it is viewer-independent (the raw
// ball_in_court field is a user UUID this builder cannot resolve to a name). It
// says which side owes the next move on the submittal.
function courtLabel(status: string, t: Translate): string {
  if (DONE_STATUSES.includes(status)) {
    return t('submittals.insights.court_done', { defaultValue: 'Closed out' });
  }
  if (status === 'draft') {
    return t('submittals.insights.court_submit', { defaultValue: 'Awaiting submission' });
  }
  if (status === 'revise_and_resubmit') {
    return t('submittals.insights.court_resubmit', { defaultValue: 'Awaiting resubmission' });
  }
  return t('submittals.insights.court_review', { defaultValue: 'Awaiting review' });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  status: string;
  type: string;
  spec: string;
  court: string;
  month: string;
  age: number;
  open: number;
  overdue: number;
  // Number for an approved submittal, '' otherwise. The panel excludes '' cells
  // from an average (toNumber('') is null), so the avg KPI over this column is a
  // clean turnaround over approved submittals only.
  days_to_approve: number | string;
}

function toRow(r: SubmittalLite, t: Translate): Row {
  const done = DONE_STATUSES.includes(r.status);
  const approved = APPROVED_STATUSES.includes(r.status);
  const open = done ? 0 : 1;
  const dueRaw = r.date_required ? parseDateUTC(r.date_required).getTime() : NaN;
  const overdue = open === 1 && !Number.isNaN(dueRaw) && dueRaw < Date.now() ? 1 : 0;
  const turnaround = daysOpen(r);
  return {
    title: r.title ?? '',
    status: statusLabel(r.status, t),
    type: typeLabel(r.type, t),
    spec: specLabel(r.spec_section, t),
    court: courtLabel(r.status, t),
    month: monthKey(r.created_at),
    age: turnaround,
    open,
    overdue,
    days_to_approve: approved ? turnaround : '',
  };
}

export interface SubmittalsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildSubmittalsInsights(
  submittals: SubmittalLite[],
  currency: string,
  t: Translate,
): SubmittalsInsights {
  const rows: Row[] = [...submittals]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'submittals',
    label: t('submittals.insights.ds_submittals', { defaultValue: 'Submittal register' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('submittals.insights.f_title', { defaultValue: 'Submittal' }), kind: 'dimension' },
      { key: 'status', label: t('submittals.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'type', label: t('submittals.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'spec', label: t('submittals.insights.f_spec', { defaultValue: 'Spec section' }), kind: 'dimension' },
      { key: 'court', label: t('submittals.insights.f_court', { defaultValue: 'Ball in court' }), kind: 'dimension' },
      { key: 'month', label: t('submittals.insights.f_month', { defaultValue: 'Month raised' }), kind: 'dimension' },
      { key: 'age', label: t('submittals.insights.f_age', { defaultValue: 'Days open' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('submittals.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('submittals.insights.f_overdue', { defaultValue: 'Overdue' }), kind: 'measure', format: 'number' },
      { key: 'days_to_approve', label: t('submittals.insights.f_days_to_approve', { defaultValue: 'Days to approve' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'submittals', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-submittals', title: t('submittals.insights.k_submittals', { defaultValue: 'Submittals' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('submittals.insights.k_open', { defaultValue: 'Open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-overdue', title: t('submittals.insights.k_overdue', { defaultValue: 'Overdue' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-avg-age', title: t('submittals.insights.k_avg_age', { defaultValue: 'Avg days open' }), chart: 'kpi', measure: 'age', agg: 'avg', color: 4 },
    { ...base, id: 'kpi-avg-approve', title: t('submittals.insights.k_avg_approve', { defaultValue: 'Avg days to approve' }), chart: 'kpi', measure: 'days_to_approve', agg: 'avg', color: 3 },
    { ...base, id: 'bar-by-type', title: t('submittals.insights.c_by_type', { defaultValue: 'Submittals by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('submittals.insights.c_by_status', { defaultValue: 'Submittals by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-court', title: t('submittals.insights.c_by_court', { defaultValue: 'Who owes the next move' }), chart: 'bar', dimension: 'court', agg: 'count', color: 1 },
    { ...base, id: 'area-over-time', title: t('submittals.insights.c_over_time', { defaultValue: 'Submittals raised over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
