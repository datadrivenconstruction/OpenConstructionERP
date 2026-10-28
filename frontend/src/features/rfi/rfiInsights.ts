// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RFI register's contribution to the Module Insights panel: it turns the RFIs
 * the page already loaded into one dataset plus a set of built-in KPIs and
 * charts (RFIs by discipline, by status, who currently owes the next move, and
 * how many are raised over time). When a project has no RFIs yet, the panel
 * simply stays empty until the register holds records.
 *
 * Value labels reuse the same `rfi.status_*` / `rfi.priority_*` /
 * `rfi.discipline_*` i18n keys the register table uses, so a slice in a chart
 * reads exactly like the badge on the row it came from. These are count / age
 * / status insights: an RFI carries no money field, so every measure is a plain
 * number (a count, a day count or a 0/1 flag) - there is no currency KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

// English fallbacks for the computed `rfi.status_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const RFI_STATUS_LABELS: Record<string, string> = {
  draft: 'Draft', open: 'Open', answered: 'Answered', closed: 'Closed', void: 'Void'
};


type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from an RFI. The page hands it the full
// RFI[] (structurally a superset of this), so no mapping is needed at the call
// site. `days_open` is optional so a row that arrives without the server-derived
// counter falls back to computing the age from `created_at`.
interface RFILite {
  subject: string;
  status: string;
  priority: string | null;
  discipline: string | null;
  created_at: string;
  is_overdue: boolean;
  days_open?: number;
}

// draft/open still need an answer; answered is waiting on the originator to
// verify and close it out; closed/void are done.
const DONE_STATUSES = ['closed', 'void'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Whole days between an ISO timestamp and now (never negative). Fallback for a
 *  row that arrives without the server's `days_open`. */
function daysSince(iso: string): number {
  const start = new Date(iso).getTime();
  if (Number.isNaN(start)) return 0;
  return Math.max(0, Math.floor((Date.now() - start) / 86_400_000));
}

function statusLabel(code: string, t: Translate): string {
  return t(`rfi.status_${code}`, { defaultValue: RFI_STATUS_LABELS[code] ?? code.charAt(0).toUpperCase() + code.slice(1) });
}

function priorityLabel(code: string | null, t: Translate): string {
  if (!code) return t('rfi.insights.no_priority', { defaultValue: 'No priority' });
  return t(`rfi.priority_${code}`, { defaultValue: code.charAt(0).toUpperCase() + code.slice(1) });
}

function disciplineLabel(code: string | null, t: Translate): string {
  if (!code) return t('rfi.discipline_none', { defaultValue: 'No discipline' });
  return t(`rfi.discipline_${code}`, { defaultValue: code.charAt(0).toUpperCase() + code.slice(1) });
}

// Ball-in-court derived from status alone, so it is viewer-independent (unlike
// the row's "With you / With them" badge, which needs the current user id). The
// raw `ball_in_court` field is a user UUID this builder cannot resolve to a
// name, so the readable signal is which side owes the next move.
function courtLabel(status: string, t: Translate): string {
  if (DONE_STATUSES.includes(status)) return t('rfi.insights.court_done', { defaultValue: 'Closed out' });
  if (status === 'answered') return t('rfi.insights.court_closeout', { defaultValue: 'Awaiting closeout' });
  return t('rfi.insights.court_answer', { defaultValue: 'Awaiting answer' });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  subject: string;
  status: string;
  priority: string;
  discipline: string;
  court: string;
  month: string;
  age: number;
  open: number;
  overdue: number;
}

function toRow(r: RFILite, t: Translate): Row {
  return {
    subject: r.subject ?? '',
    status: statusLabel(r.status, t),
    priority: priorityLabel(r.priority, t),
    discipline: disciplineLabel(r.discipline, t),
    court: courtLabel(r.status, t),
    month: monthKey(r.created_at),
    age: typeof r.days_open === 'number' ? r.days_open : daysSince(r.created_at),
    open: r.status === 'open' ? 1 : 0,
    overdue: r.is_overdue ? 1 : 0,
  };
}

export interface RFIInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildRFIInsights(
  rfis: RFILite[],
  currency: string,
  t: Translate,
): RFIInsights {
  const rows: Row[] = [...rfis]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'rfis',
    label: t('rfi.insights.ds_rfis', { defaultValue: 'RFI register' }),
    currency: currency || '',
    fields: [
      { key: 'subject', label: t('rfi.insights.f_subject', { defaultValue: 'RFI' }), kind: 'dimension' },
      { key: 'status', label: t('rfi.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'priority', label: t('rfi.insights.f_priority', { defaultValue: 'Priority' }), kind: 'dimension' },
      { key: 'discipline', label: t('rfi.insights.f_discipline', { defaultValue: 'Discipline' }), kind: 'dimension' },
      { key: 'court', label: t('rfi.insights.f_court', { defaultValue: 'Ball in court' }), kind: 'dimension' },
      { key: 'month', label: t('rfi.insights.f_month', { defaultValue: 'Month raised' }), kind: 'dimension' },
      { key: 'age', label: t('rfi.insights.f_age', { defaultValue: 'Days open' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('rfi.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('rfi.insights.f_overdue', { defaultValue: 'Overdue' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'rfis', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-rfis', title: t('rfi.insights.k_rfis', { defaultValue: 'RFIs' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('rfi.insights.k_open', { defaultValue: 'Open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-overdue', title: t('rfi.insights.k_overdue', { defaultValue: 'Overdue' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-avg-age', title: t('rfi.insights.k_avg_age', { defaultValue: 'Avg days open' }), chart: 'kpi', measure: 'age', agg: 'avg', color: 4 },
    { ...base, id: 'bar-by-discipline', title: t('rfi.insights.c_by_discipline', { defaultValue: 'RFIs by discipline' }), chart: 'bar', dimension: 'discipline', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('rfi.insights.c_by_status', { defaultValue: 'RFIs by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-court', title: t('rfi.insights.c_by_court', { defaultValue: 'Who owes the next move' }), chart: 'bar', dimension: 'court', agg: 'count', color: 1 },
    { ...base, id: 'area-over-time', title: t('rfi.insights.c_over_time', { defaultValue: 'RFIs raised over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
