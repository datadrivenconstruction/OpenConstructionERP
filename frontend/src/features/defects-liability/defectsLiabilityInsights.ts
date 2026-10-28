// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Defects-liability register's contribution to the Module Insights panel: it
 * turns the defect notices the page already loaded into one dataset plus a set
 * of built-in KPIs and charts (defects by status, by severity, who owns the
 * rectification, and how many are raised over time). When a project has no
 * defect notices yet, the panel simply stays empty until the register holds
 * records.
 *
 * Value labels reuse the same `defects_liability.defect_status_*` and
 * `defects_liability.defect_severity_*` i18n keys the register table uses, so a
 * slice in a chart reads exactly like the badge on the row it came from. A
 * defect carries no money field, so every measure is a plain number (a count, a
 * day count or a 0/1 flag) - there is no currency KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import { parseDateUTC } from '@/shared/lib/dates';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from a defect notice. The page hands it the
// full Defect[] (structurally a superset of this), so no mapping is needed at
// the call site.
interface DefectLite {
  reference: string;
  severity: string | null;
  status: string;
  raised_date: string | null;
  due_date: string | null;
  rectified_date: string | null;
  responsible_party: string | null;
  created_at: string;
}

// A defect is still live while open or being rectified; it is closed out once
// rectified, rejected or closed. Mirrors the register's own open/overdue logic
// (DefectsLiabilityPage.isDefectOverdue treats open/rectifying as active).
const OPEN_STATUSES = ['open', 'rectifying'];
const DONE_STATUSES = ['rectified', 'rejected', 'closed'];

const DAY_MS = 86_400_000;

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

function statusLabel(code: string, t: Translate): string {
  return t(`defects_liability.defect_status_${code}`, { defaultValue: humanize(code) });
}

// Reuse the register's own "Unset" label for a defect with no severity, so the
// slice matches the dropdown option the table uses for the same case.
function severityLabel(code: string | null, t: Translate): string {
  const c = code?.trim();
  if (!c) return t('defects_liability.defect_severity_none', { defaultValue: 'Unset' });
  return t(`defects_liability.defect_severity_${c}`, { defaultValue: humanize(c) });
}

function responsibleLabel(party: string | null, t: Translate): string {
  const p = party?.trim();
  return p ? p : t('defects_liability.insights.unassigned', { defaultValue: 'Unassigned' });
}

/** Whole days the defect has been (or was) open: raised -> now for a live one,
 *  raised -> rectified for a rectified one. Never negative. Falls back to
 *  created_at when raised_date is missing. */
function daysOpen(d: DefectLite): number {
  const start = new Date(d.raised_date ?? d.created_at).getTime();
  if (Number.isNaN(start)) return 0;
  const done = DONE_STATUSES.includes(d.status);
  const endRaw = done && d.rectified_date ? new Date(d.rectified_date).getTime() : Date.now();
  const end = Number.isNaN(endRaw) ? Date.now() : endRaw;
  return Math.max(0, Math.floor((end - start) / DAY_MS));
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  reference: string;
  status: string;
  severity: string;
  responsible: string;
  month: string;
  age: number;
  open: number;
  overdue: number;
  closed: number;
  // Number for a rectified defect, '' otherwise. The panel excludes '' cells
  // from an average (toNumber('') is null), so the avg KPI over this column is a
  // clean turnaround over rectified defects only.
  days_to_rectify: number | string;
}

function toRow(d: DefectLite, t: Translate): Row {
  const open = OPEN_STATUSES.includes(d.status) ? 1 : 0;
  const done = DONE_STATUSES.includes(d.status);
  const dueRaw = d.due_date ? parseDateUTC(d.due_date).getTime() : NaN;
  const overdue = open === 1 && !Number.isNaN(dueRaw) && dueRaw < Date.now() ? 1 : 0;

  let daysToRectify: number | string = '';
  if (d.rectified_date) {
    const start = new Date(d.raised_date ?? d.created_at).getTime();
    const rectified = new Date(d.rectified_date).getTime();
    if (!Number.isNaN(start) && !Number.isNaN(rectified)) {
      daysToRectify = Math.max(0, Math.floor((rectified - start) / DAY_MS));
    }
  }

  return {
    reference: d.reference ?? '',
    status: statusLabel(d.status, t),
    severity: severityLabel(d.severity, t),
    responsible: responsibleLabel(d.responsible_party, t),
    month: monthKey(d.raised_date ?? d.created_at),
    age: daysOpen(d),
    open,
    overdue,
    closed: done ? 1 : 0,
    days_to_rectify: daysToRectify,
  };
}

export interface DefectsLiabilityInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildDefectsLiabilityInsights(
  defects: DefectLite[],
  currency: string,
  t: Translate,
): DefectsLiabilityInsights {
  const rows: Row[] = [...defects]
    .sort(
      (a, b) =>
        new Date(a.raised_date ?? a.created_at).getTime() -
        new Date(b.raised_date ?? b.created_at).getTime(),
    )
    .map((d) => toRow(d, t));

  const dataset: InsightDataset = {
    id: 'defects',
    label: t('defects_liability.insights.ds_defects', { defaultValue: 'Defect register' }),
    currency: currency || '',
    fields: [
      { key: 'reference', label: t('defects_liability.insights.f_reference', { defaultValue: 'Reference' }), kind: 'dimension' },
      { key: 'status', label: t('defects_liability.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'severity', label: t('defects_liability.insights.f_severity', { defaultValue: 'Severity' }), kind: 'dimension' },
      { key: 'responsible', label: t('defects_liability.insights.f_responsible', { defaultValue: 'Responsible party' }), kind: 'dimension' },
      { key: 'month', label: t('defects_liability.insights.f_month', { defaultValue: 'Month raised' }), kind: 'dimension' },
      { key: 'age', label: t('defects_liability.insights.f_age', { defaultValue: 'Days open' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('defects_liability.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('defects_liability.insights.f_overdue', { defaultValue: 'Overdue' }), kind: 'measure', format: 'number' },
      { key: 'closed', label: t('defects_liability.insights.f_closed', { defaultValue: 'Closed out' }), kind: 'measure', format: 'number' },
      { key: 'days_to_rectify', label: t('defects_liability.insights.f_days_to_rectify', { defaultValue: 'Days to rectify' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'defects', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-defects', title: t('defects_liability.insights.k_defects', { defaultValue: 'Defects' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('defects_liability.insights.k_open', { defaultValue: 'Open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-overdue', title: t('defects_liability.insights.k_overdue', { defaultValue: 'Overdue' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-avg-age', title: t('defects_liability.insights.k_avg_age', { defaultValue: 'Avg days open' }), chart: 'kpi', measure: 'age', agg: 'avg', color: 4 },
    { ...base, id: 'donut-by-status', title: t('defects_liability.insights.c_by_status', { defaultValue: 'Defects by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-severity', title: t('defects_liability.insights.c_by_severity', { defaultValue: 'Defects by severity' }), chart: 'bar', dimension: 'severity', agg: 'count', color: 1 },
    { ...base, id: 'bar-by-responsible', title: t('defects_liability.insights.c_by_responsible', { defaultValue: 'Defects by responsible party' }), chart: 'bar', dimension: 'responsible', agg: 'count', color: 0 },
    { ...base, id: 'area-over-time', title: t('defects_liability.insights.c_over_time', { defaultValue: 'Defects raised over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
