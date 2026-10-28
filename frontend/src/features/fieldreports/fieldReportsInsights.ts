// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field reports' contribution to the Module Insights panel: it turns the daily
 * site reports the page already loaded into one dataset plus a set of built-in
 * KPIs and charts (reports by type, by status, by weather, and how many reports
 * and labour hours land over time). When a project has no reports yet, the panel
 * simply stays empty until the module holds records.
 *
 * Value labels reuse the same `fieldreports.type_*` / `fieldreports.status_*` /
 * `fieldreports.weather_*` i18n keys the register uses, so a slice in a chart
 * reads exactly like the badge on the row it came from. A field report carries
 * no money field, so every measure is a plain number (a count, an hour count or
 * a 0/1 flag) - there is no currency KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

interface WorkforceLite {
  count?: number | null;
  hours?: number | null;
}

// Minimal shape this builder needs from a field report. The page hands it the
// full FieldReport[] (structurally a superset of this), so no mapping is needed
// at the call site.
interface FieldReportLite {
  report_date: string;
  report_type: string;
  weather_condition: string;
  status: string;
  workforce?: WorkforceLite[] | null;
  delay_hours?: number | null;
  created_at: string;
}

// A report is approved once it is signed off; draft and submitted are still in
// progress, so "open" is anything not yet approved.
const APPROVED_STATUS = 'approved';

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  // report_date is a date-only string (yyyy-mm-dd); new Date() would read it as
  // UTC midnight and drift the month back a day for viewers west of UTC. Anchor
  // bare dates to local midnight (as the page's formatDate helper does); full
  // timestamps already carry their own time.
  const s = iso.length === 10 ? `${iso}T00:00:00` : iso;
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return 'n/a';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Reasonable title-case fallback; the real translation wins when present. */
function humanize(code: string): string {
  const s = code.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function typeLabel(code: string, t: Translate): string {
  return t(`fieldreports.type_${code}`, { defaultValue: humanize(code) });
}

function statusLabel(code: string, t: Translate): string {
  return t(`fieldreports.status_${code}`, { defaultValue: humanize(code) });
}

function weatherLabel(code: string, t: Translate): string {
  return t(`fieldreports.weather_${code}`, { defaultValue: humanize(code) });
}

/** Total headcount and labour hours across the report's workforce rows. */
function workforceTotals(
  wf: WorkforceLite[] | null | undefined,
): { workers: number; hours: number } {
  let workers = 0;
  let hours = 0;
  for (const e of wf ?? []) {
    const c = e.count ?? 0;
    workers += c;
    hours += c * (e.hours ?? 0);
  }
  return { workers, hours: Math.round(hours * 10) / 10 };
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  date: string;
  type: string;
  status: string;
  weather: string;
  month: string;
  workers: number;
  labour: number;
  delay: number;
  open: number;
  approved: number;
}

function toRow(r: FieldReportLite, t: Translate): Row {
  const { workers, hours } = workforceTotals(r.workforce);
  const approved = r.status === APPROVED_STATUS ? 1 : 0;
  return {
    date: r.report_date ?? '',
    type: typeLabel(r.report_type, t),
    status: statusLabel(r.status, t),
    weather: weatherLabel(r.weather_condition, t),
    month: monthKey(r.report_date || r.created_at),
    workers,
    labour: hours,
    delay: r.delay_hours ?? 0,
    open: approved ? 0 : 1,
    approved,
  };
}

export interface FieldReportsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildFieldReportsInsights(
  reports: FieldReportLite[],
  currency: string,
  t: Translate,
): FieldReportsInsights {
  const rows: Row[] = [...reports]
    .sort((a, b) => new Date(a.report_date).getTime() - new Date(b.report_date).getTime())
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'fieldreports',
    label: t('fieldreports.insights.ds_reports', { defaultValue: 'Field reports' }),
    currency: currency || '',
    fields: [
      { key: 'date', label: t('fieldreports.insights.f_date', { defaultValue: 'Report date' }), kind: 'dimension' },
      { key: 'type', label: t('fieldreports.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('fieldreports.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'weather', label: t('fieldreports.insights.f_weather', { defaultValue: 'Weather' }), kind: 'dimension' },
      { key: 'month', label: t('fieldreports.insights.f_month', { defaultValue: 'Month' }), kind: 'dimension' },
      { key: 'workers', label: t('fieldreports.insights.f_workers', { defaultValue: 'Workers' }), kind: 'measure', format: 'number' },
      { key: 'labour', label: t('fieldreports.insights.f_labour', { defaultValue: 'Labour hours' }), kind: 'measure', format: 'number' },
      { key: 'delay', label: t('fieldreports.insights.f_delay', { defaultValue: 'Delay hours' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('fieldreports.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'approved', label: t('fieldreports.insights.f_approved', { defaultValue: 'Approved' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'fieldreports', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-reports', title: t('fieldreports.insights.k_reports', { defaultValue: 'Reports' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-labour', title: t('fieldreports.insights.k_labour', { defaultValue: 'Labour hours' }), chart: 'kpi', measure: 'labour', agg: 'sum', color: 3 },
    { ...base, id: 'kpi-delay', title: t('fieldreports.insights.k_delay', { defaultValue: 'Delay hours' }), chart: 'kpi', measure: 'delay', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-approved', title: t('fieldreports.insights.k_approved', { defaultValue: 'Approved' }), chart: 'kpi', measure: 'approved', agg: 'sum', color: 6 },
    { ...base, id: 'bar-by-type', title: t('fieldreports.insights.c_by_type', { defaultValue: 'Reports by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('fieldreports.insights.c_by_status', { defaultValue: 'Reports by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-weather', title: t('fieldreports.insights.c_by_weather', { defaultValue: 'Reports by weather' }), chart: 'bar', dimension: 'weather', agg: 'count', color: 3 },
    { ...base, id: 'area-over-time', title: t('fieldreports.insights.c_over_time', { defaultValue: 'Reports logged over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
    { ...base, id: 'line-labour-over-time', title: t('fieldreports.insights.c_labour_over_time', { defaultValue: 'Labour hours over time' }), chart: 'line', dimension: 'month', measure: 'labour', agg: 'sum', color: 6 },
  ];

  return { datasets: [dataset], builtins };
}
