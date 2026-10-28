// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Risk register's contribution to the Module Insights panel: it turns the
 * risks the page already loaded into one dataset plus a set of built-in KPIs
 * and charts (exposure by category, risks by severity and status, register
 * growth over time). When a project has no risks yet, the panel simply stays
 * empty until the register holds records.
 *
 * Labels reuse the same `risk.cat_*` / `risk.severity_*` / `risk.status_*`
 * i18n keys the register table uses, so a slice in a chart reads exactly like
 * the badge on the row it came from.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

// English fallbacks for the computed `risk.cat_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const RISK_CAT_LABELS: Record<string, string> = {
  technical: 'Technical', financial: 'Financial', schedule: 'Schedule', regulatory: 'Regulatory',
  environmental: 'Environmental', safety: 'Safety', procurement: 'Procurement'
};

// English fallbacks for the computed `risk.status_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const RISK_STATUS_LABELS: Record<string, string> = {
  identified: 'Identified', assessed: 'Assessed', mitigating: 'Mitigating', monitoring: 'Monitoring',
  mitigated: 'Mitigated', open: 'Open', closed: 'Closed', occurred: 'Occurred'
};


type Translate = ReturnType<typeof useTranslation>['t'];

interface RiskLite {
  title: string;
  category: string;
  impact_severity: string;
  status: string;
  risk_score: number;
  impact_cost: number;
  impact_schedule_days: number;
  owner_name: string;
  created_at: string;
}

const HIGH_SEVERITIES = ['high', 'critical'];
const MITIGATED_STATUSES = ['mitigating', 'mitigated', 'closed'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function catLabel(code: string, t: Translate): string {
  return t(`risk.cat_${code}`, { defaultValue: RISK_CAT_LABELS[code] ?? code.charAt(0).toUpperCase() + code.slice(1) });
}

function severityLabel(code: string, t: Translate): string {
  return t(`risk.severity_${code}`, { defaultValue: code.charAt(0).toUpperCase() + code.slice(1) });
}

function statusLabel(code: string, t: Translate): string {
  return t(`risk.status_${code}`, { defaultValue: RISK_STATUS_LABELS[code] ?? code.charAt(0).toUpperCase() + code.slice(1) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  category: string;
  severity: string;
  status: string;
  owner: string;
  month: string;
  exposure: number;
  score: number;
  schedule: number;
  high: number;
  mitigated: number;
}

function toRow(r: RiskLite, unassigned: string, t: Translate): Row {
  return {
    title: r.title ?? '',
    category: catLabel(r.category, t),
    severity: severityLabel(r.impact_severity, t),
    status: statusLabel(r.status, t),
    owner: r.owner_name?.trim() || unassigned,
    month: monthKey(r.created_at),
    exposure: r.impact_cost ?? 0,
    score: r.risk_score ?? 0,
    schedule: r.impact_schedule_days ?? 0,
    high: HIGH_SEVERITIES.includes(r.impact_severity) ? 1 : 0,
    mitigated: MITIGATED_STATUSES.includes(r.status) ? 1 : 0,
  };
}

export interface RiskInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildRiskInsights(
  risks: RiskLite[],
  currency: string,
  t: Translate,
): RiskInsights {
  const unassigned = t('risk.insights.unassigned', { defaultValue: 'Unassigned' });

  const rows: Row[] = [...risks]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, unassigned, t));

  const dataset: InsightDataset = {
    id: 'risks',
    label: t('risk.insights.ds_risks', { defaultValue: 'Risk register' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('risk.insights.f_title', { defaultValue: 'Risk' }), kind: 'dimension' },
      { key: 'category', label: t('risk.insights.f_category', { defaultValue: 'Category' }), kind: 'dimension' },
      { key: 'severity', label: t('risk.insights.f_severity', { defaultValue: 'Severity' }), kind: 'dimension' },
      { key: 'status', label: t('risk.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'owner', label: t('risk.insights.f_owner', { defaultValue: 'Owner' }), kind: 'dimension' },
      { key: 'month', label: t('risk.insights.f_month', { defaultValue: 'Month logged' }), kind: 'dimension' },
      { key: 'exposure', label: t('risk.insights.f_exposure', { defaultValue: 'Cost impact (unweighted)' }), kind: 'measure', format: 'currency' },
      { key: 'score', label: t('risk.insights.f_score', { defaultValue: 'Risk score' }), kind: 'measure', format: 'number' },
      { key: 'schedule', label: t('risk.insights.f_schedule', { defaultValue: 'Schedule impact (days)' }), kind: 'measure', format: 'number' },
      { key: 'high', label: t('risk.insights.f_high', { defaultValue: 'High / Critical' }), kind: 'measure', format: 'number' },
      { key: 'mitigated', label: t('risk.insights.f_mitigated', { defaultValue: 'Mitigated' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'risks', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-risks', title: t('risk.insights.k_risks', { defaultValue: 'Risks' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-exposure', title: t('risk.insights.k_exposure', { defaultValue: 'Total impact (unweighted)' }), chart: 'kpi', measure: 'exposure', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-avg-score', title: t('risk.insights.k_avgscore', { defaultValue: 'Avg risk score' }), chart: 'kpi', measure: 'score', agg: 'avg', color: 4 },
    { ...base, id: 'kpi-high', title: t('risk.insights.k_high', { defaultValue: 'High / Critical' }), chart: 'kpi', measure: 'high', agg: 'sum', color: 1 },
    { ...base, id: 'bar-exposure-by-cat', title: t('risk.insights.c_exposure_by_cat', { defaultValue: 'Impact by category' }), chart: 'bar', dimension: 'category', measure: 'exposure', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-severity', title: t('risk.insights.c_by_severity', { defaultValue: 'Risks by severity' }), chart: 'donut', dimension: 'severity', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-status', title: t('risk.insights.c_by_status', { defaultValue: 'Risks by status' }), chart: 'bar', dimension: 'status', agg: 'count', color: 0 },
    { ...base, id: 'area-over-time', title: t('risk.insights.c_over_time', { defaultValue: 'Risks logged over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
