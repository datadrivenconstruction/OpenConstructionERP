// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Management of Change's contribution to the Module Insights panel: it turns
 * the change requests the page already loaded into one dataset plus a set of
 * built-in KPIs and charts (cost impact by category, changes by status and
 * risk level, register growth over time). When a project has no changes yet,
 * the panel simply stays empty until the register holds records.
 *
 * Labels reuse the same `moc.status_*`, `moc.category_*` and `moc.risk_*` i18n
 * keys the register uses, so a slice in a chart reads exactly like the badge on
 * the row it came from.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

// English fallbacks for the computed `moc.status_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const MOC_STATUS_LABELS: Record<string, string> = {
  proposed: 'Proposed', reviewed: 'Reviewed', accepted: 'Accepted', declined: 'Declined',
  implemented: 'Implemented'
};


// English fallbacks for the computed `moc.category_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const MOC_CATEGORY_LABELS: Record<string, string> = {
  engineering: 'Engineering', scope: 'Scope', design: 'Design', process: 'Process', material: 'Material',
  safety: 'Safety', organizational: 'Organisational', regulatory: 'Regulatory', other: 'Other'
};


type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from a change request. The page's `MoCEntry`
 * type structurally satisfies this (the money field stays `number | string` so
 * the raw record is assignable without a cast).
 */
interface MoCLite {
  code?: string;
  title?: string;
  status?: string;
  change_category?: string;
  risk_level?: string;
  cost_impact?: number | string;
  schedule_delta_days?: number;
  currency?: string;
  proposed_at?: string | null;
}

// Statuses that mean the change is still open on the reviewer's desk.
const OPEN_STATUSES = ['proposed', 'reviewed'];
// Risk bands that warrant management attention.
const HIGH_RISKS = ['high', 'critical'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'n/a';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Fallback for an unknown code: "risk_assessment" -> "Risk assessment". */
function humanize(code: string): string {
  const spaced = code.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced;
}

/** Reuse the register's own `moc.status_*` keys so a chart slice reads exactly
 *  like the status badge on the row it came from. */
function statusLabel(code: string, t: Translate): string {
  return t(`moc.status_${code}`, { defaultValue: MOC_STATUS_LABELS[code] ?? humanize(code) });
}

/** Reuse the register's own `moc.category_*` keys. */
function categoryLabel(code: string, t: Translate): string {
  return t(`moc.category_${code}`, { defaultValue: MOC_CATEGORY_LABELS[code] ?? humanize(code) });
}

/** Reuse the register's own `moc.risk_*` keys. */
function riskLabel(code: string, t: Translate): string {
  return t(`moc.risk_${code}`, { defaultValue: humanize(code) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  code: string;
  title: string;
  status: string;
  category: string;
  risk: string;
  month: string;
  cost: number;
  schedule: number;
  open: number;
  accepted: number;
  implemented: number;
  highrisk: number;
}

function toRow(e: MoCLite, t: Translate): Row {
  const status = e.status ?? '';
  const risk = e.risk_level ?? '';
  return {
    code: e.code ?? '',
    title: e.title ?? '',
    status: statusLabel(status, t),
    category: categoryLabel(e.change_category ?? 'other', t),
    risk: riskLabel(risk || 'medium', t),
    month: monthKey(e.proposed_at ?? ''),
    cost: Number(e.cost_impact) || 0,
    schedule: Number(e.schedule_delta_days) || 0,
    open: OPEN_STATUSES.includes(status) ? 1 : 0,
    accepted: status === 'accepted' ? 1 : 0,
    implemented: status === 'implemented' ? 1 : 0,
    highrisk: HIGH_RISKS.includes(risk) ? 1 : 0,
  };
}

export interface MocInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildMocInsights(
  entries: MoCLite[],
  currency: string,
  t: Translate,
): MocInsights {
  const dateOf = (e: MoCLite): number => new Date(e.proposed_at ?? '').getTime();

  const rows: Row[] = [...entries]
    .sort((a, b) => (dateOf(a) || 0) - (dateOf(b) || 0))
    .map((e) => toRow(e, t));

  const dataset: InsightDataset = {
    id: 'moc',
    label: t('moc.insights.ds_changes', { defaultValue: 'Change requests' }),
    currency: currency || '',
    fields: [
      { key: 'code', label: t('moc.insights.f_code', { defaultValue: 'Change' }), kind: 'dimension' },
      { key: 'status', label: t('moc.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'category', label: t('moc.insights.f_category', { defaultValue: 'Category' }), kind: 'dimension' },
      { key: 'risk', label: t('moc.insights.f_risk', { defaultValue: 'Risk level' }), kind: 'dimension' },
      { key: 'month', label: t('moc.insights.f_month', { defaultValue: 'Month proposed' }), kind: 'dimension' },
      { key: 'cost', label: t('moc.insights.f_cost', { defaultValue: 'Cost impact' }), kind: 'measure', format: 'currency' },
      { key: 'schedule', label: t('moc.insights.f_schedule', { defaultValue: 'Schedule impact (days)' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('moc.insights.f_open', { defaultValue: 'Under review' }), kind: 'measure', format: 'number' },
      { key: 'accepted', label: t('moc.insights.f_accepted', { defaultValue: 'Accepted' }), kind: 'measure', format: 'number' },
      { key: 'implemented', label: t('moc.insights.f_implemented', { defaultValue: 'Implemented' }), kind: 'measure', format: 'number' },
      { key: 'highrisk', label: t('moc.insights.f_highrisk', { defaultValue: 'High / Critical' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'moc', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-changes', title: t('moc.insights.k_changes', { defaultValue: 'Change requests' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-cost', title: t('moc.insights.k_cost', { defaultValue: 'Total cost impact' }), chart: 'kpi', measure: 'cost', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-open', title: t('moc.insights.k_open', { defaultValue: 'Under review' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-highrisk', title: t('moc.insights.k_highrisk', { defaultValue: 'High / Critical' }), chart: 'kpi', measure: 'highrisk', agg: 'sum', color: 4 },
    { ...base, id: 'bar-cost-by-category', title: t('moc.insights.c_cost_by_category', { defaultValue: 'Cost impact by category' }), chart: 'bar', dimension: 'category', measure: 'cost', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-status', title: t('moc.insights.c_by_status', { defaultValue: 'Changes by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-risk', title: t('moc.insights.c_by_risk', { defaultValue: 'Changes by risk level' }), chart: 'bar', dimension: 'risk', agg: 'count', color: 0 },
    { ...base, id: 'area-over-time', title: t('moc.insights.c_over_time', { defaultValue: 'Changes proposed over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
