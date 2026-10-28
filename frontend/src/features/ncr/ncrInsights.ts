// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * NCR register's contribution to the Module Insights panel: it turns the
 * non-conformance reports the page already loaded into one dataset plus a set
 * of built-in KPIs and charts (NCRs by type, by severity, by status and how
 * many are raised over time). When a project has no NCRs yet, the panel
 * simply stays empty until the register holds records.
 *
 * Value labels reuse the same `ncr.type_*` / `ncr.severity_*` / `ncr.status_*`
 * i18n keys the register table uses, so a slice in a chart reads exactly like
 * the badge on the row it came from. These are count / severity / age
 * insights: every measure is a plain number (a count, an age in days or a 0/1
 * flag). NCRs do carry a cost-impact field, but by design this panel stays a
 * quality-and-ageing view and never turns it into a money KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

// English fallbacks for the computed `ncr.severity_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const NCR_SEVERITY_LABELS: Record<string, string> = {
  critical: 'Critical', major: 'Major', minor: 'Minor', observation: 'Observation'
};


type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from an NCR. The page hands it the full
// NCR[] (structurally a superset of this), so no mapping is needed at the call
// site. There is no discipline field on an NCR, so the trade breakdown is by
// type instead.
interface NCRLite {
  title: string;
  ncr_type: string;
  severity: string;
  status: string;
  created_at: string;
  closed_at: string | null;
}

// critical/major are the ones that need a manager's attention now; closed/void
// are off the active list.
const HIGH_SEVERITIES = ['critical', 'major'];
const DONE_STATUSES = ['closed', 'void'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Whole days a report has been alive: created until it was closed, or until
 *  now while it is still open (never negative). */
function ageDays(created: string, closed: string | null): number {
  const start = new Date(created).getTime();
  if (Number.isNaN(start)) return 0;
  const rawEnd = closed ? new Date(closed).getTime() : Date.now();
  const end = Number.isNaN(rawEnd) ? Date.now() : rawEnd;
  return Math.max(0, Math.floor((end - start) / 86_400_000));
}

function typeLabel(code: string, t: Translate): string {
  return t(`ncr.type_${code}`, { defaultValue: code.charAt(0).toUpperCase() + code.slice(1) });
}

function severityLabel(code: string, t: Translate): string {
  return t(`ncr.severity_${code}`, { defaultValue: NCR_SEVERITY_LABELS[code] ?? code.charAt(0).toUpperCase() + code.slice(1) });
}

function statusLabel(code: string, t: Translate): string {
  return t(`ncr.status_${code}`, { defaultValue: code.replace(/_/g, ' ') });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  type: string;
  severity: string;
  status: string;
  month: string;
  age: number;
  open: number;
  high: number;
}

function toRow(r: NCRLite, t: Translate): Row {
  return {
    title: r.title ?? '',
    type: typeLabel(r.ncr_type, t),
    severity: severityLabel(r.severity, t),
    status: statusLabel(r.status, t),
    month: monthKey(r.created_at),
    age: ageDays(r.created_at, r.closed_at),
    open: DONE_STATUSES.includes(r.status) ? 0 : 1,
    high: HIGH_SEVERITIES.includes(r.severity) ? 1 : 0,
  };
}

export interface NCRInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildNCRInsights(
  ncrs: NCRLite[],
  currency: string,
  t: Translate,
): NCRInsights {
  const rows: Row[] = [...ncrs]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'ncrs',
    label: t('ncr.insights.ds_ncrs', { defaultValue: 'NCR register' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('ncr.insights.f_title', { defaultValue: 'NCR' }), kind: 'dimension' },
      { key: 'type', label: t('ncr.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'severity', label: t('ncr.insights.f_severity', { defaultValue: 'Severity' }), kind: 'dimension' },
      { key: 'status', label: t('ncr.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'month', label: t('ncr.insights.f_month', { defaultValue: 'Month raised' }), kind: 'dimension' },
      { key: 'age', label: t('ncr.insights.f_age', { defaultValue: 'Age (days)' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('ncr.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'high', label: t('ncr.insights.f_high', { defaultValue: 'Critical / Major' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'ncrs', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-ncrs', title: t('ncr.insights.k_ncrs', { defaultValue: 'NCRs' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('ncr.insights.k_open', { defaultValue: 'Open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-high', title: t('ncr.insights.k_high', { defaultValue: 'Critical / Major' }), chart: 'kpi', measure: 'high', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-avg-age', title: t('ncr.insights.k_avg_age', { defaultValue: 'Avg age (days)' }), chart: 'kpi', measure: 'age', agg: 'avg', color: 4 },
    { ...base, id: 'bar-by-type', title: t('ncr.insights.c_by_type', { defaultValue: 'NCRs by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-severity', title: t('ncr.insights.c_by_severity', { defaultValue: 'NCRs by severity' }), chart: 'donut', dimension: 'severity', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-status', title: t('ncr.insights.c_by_status', { defaultValue: 'NCRs by status' }), chart: 'bar', dimension: 'status', agg: 'count', color: 1 },
    { ...base, id: 'area-over-time', title: t('ncr.insights.c_over_time', { defaultValue: 'NCRs raised over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
