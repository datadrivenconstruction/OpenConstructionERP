// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Quality inspections' contribution to the Module Insights panel: it turns the
 * inspections the page already loaded into one dataset plus a set of built-in
 * KPIs and charts (inspections by type, by result, by status, and how many are
 * carried out over time). When a project has no inspections yet, the panel
 * simply stays empty until the module holds records.
 *
 * Value labels reuse the same `inspections.status_*` / `inspections.type_*` /
 * `inspections.result_*` i18n keys the register table uses, so a slice in a
 * chart reads exactly like the badge on the row it came from. These are count /
 * status insights: an inspection carries no money field, so every measure is a
 * plain number (a count, a 0/1 flag, or a 0/100 pass-rate) - there is no
 * currency KPI. Pass rate is passed over all inspections, rendered as a
 * percentage.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from an inspection. The page hands it the
// full Inspection[] (structurally a superset of this), so no mapping is needed
// at the call site.
interface InspectionLite {
  title: string;
  status: string;
  inspection_type: string;
  result: string | null;
  date: string;
  created_at: string;
}

// scheduled / in_progress inspections still have to be carried out or finished;
// completed / failed / cancelled are done and no longer open.
const OPEN_STATUSES = ['scheduled', 'in_progress'];

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
  return t(`inspections.status_${code}`, { defaultValue: humanize(code) });
}

function typeLabel(code: string, t: Translate): string {
  return t(`inspections.type_${code}`, { defaultValue: humanize(code) });
}

function resultLabel(code: string | null, t: Translate): string {
  if (!code) return t('inspections.insights.no_result', { defaultValue: 'Not recorded' });
  return t(`inspections.result_${code}`, { defaultValue: humanize(code) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  status: string;
  type: string;
  result: string;
  month: string;
  passed: number;
  failed: number;
  open: number;
  // 0 or 100 so the panel's percent format reads the average of this column
  // straight as a pass-rate percentage (passed / all inspections); the percent
  // formatter appends "%" without scaling, so the value must already be 0-100.
  pass_rate: number;
}

function toRow(r: InspectionLite, t: Translate): Row {
  return {
    title: r.title ?? '',
    status: statusLabel(r.status, t),
    type: typeLabel(r.inspection_type, t),
    result: resultLabel(r.result, t),
    month: monthKey(r.date || r.created_at),
    passed: r.result === 'pass' ? 1 : 0,
    failed: r.result === 'fail' ? 1 : 0,
    open: OPEN_STATUSES.includes(r.status) ? 1 : 0,
    pass_rate: r.result === 'pass' ? 100 : 0,
  };
}

export interface InspectionsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildInspectionsInsights(
  inspections: InspectionLite[],
  currency: string,
  t: Translate,
): InspectionsInsights {
  const rows: Row[] = [...inspections]
    .sort(
      (a, b) =>
        new Date(a.date || a.created_at).getTime() - new Date(b.date || b.created_at).getTime(),
    )
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'inspections',
    label: t('inspections.insights.ds_inspections', { defaultValue: 'Inspection register' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('inspections.insights.f_title', { defaultValue: 'Inspection' }), kind: 'dimension' },
      { key: 'status', label: t('inspections.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'type', label: t('inspections.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'result', label: t('inspections.insights.f_result', { defaultValue: 'Result' }), kind: 'dimension' },
      { key: 'month', label: t('inspections.insights.f_month', { defaultValue: 'Month inspected' }), kind: 'dimension' },
      { key: 'passed', label: t('inspections.insights.f_passed', { defaultValue: 'Passed' }), kind: 'measure', format: 'number' },
      { key: 'failed', label: t('inspections.insights.f_failed', { defaultValue: 'Failed' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('inspections.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'pass_rate', label: t('inspections.insights.f_pass_rate', { defaultValue: 'Pass rate' }), kind: 'measure', format: 'percent' },
    ],
    rows,
  };

  const base = { datasetId: 'inspections', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-inspections', title: t('inspections.insights.k_inspections', { defaultValue: 'Inspections' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-passed', title: t('inspections.insights.k_passed', { defaultValue: 'Passed' }), chart: 'kpi', measure: 'passed', agg: 'sum', color: 3 },
    { ...base, id: 'kpi-failed', title: t('inspections.insights.k_failed', { defaultValue: 'Failed' }), chart: 'kpi', measure: 'failed', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-pass-rate', title: t('inspections.insights.k_pass_rate', { defaultValue: 'Pass rate' }), chart: 'kpi', measure: 'pass_rate', agg: 'avg', color: 3 },
    { ...base, id: 'bar-by-type', title: t('inspections.insights.c_by_type', { defaultValue: 'Inspections by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-result', title: t('inspections.insights.c_by_result', { defaultValue: 'Inspections by result' }), chart: 'donut', dimension: 'result', agg: 'count', color: 3 },
    { ...base, id: 'bar-by-status', title: t('inspections.insights.c_by_status', { defaultValue: 'Inspections by status' }), chart: 'bar', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'area-over-time', title: t('inspections.insights.c_over_time', { defaultValue: 'Inspections over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
