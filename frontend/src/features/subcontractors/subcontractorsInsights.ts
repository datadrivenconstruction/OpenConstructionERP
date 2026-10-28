// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Subcontractors' contribution to the Module Insights panel: it turns the
 * subcontractor register the page already loaded into one dataset plus a set
 * of built-in KPIs and charts (firms by trade, prequalification status split,
 * insurance compliance, register growth over time). When there are no
 * subcontractors yet, the panel simply stays empty until the register holds
 * records.
 *
 * Note: the `Subcontractor` list record carries no contract value - money
 * (total_value / currency) lives on the per-firm `Agreement`, which this page
 * does not load - so the measures here are the register's own real fields
 * (rating, approved / active / blocked flags), not currency sums. Each firm is
 * attributed to its first (primary) trade so counts match the firm count.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from a subcontractor row. The page's real
 * `Subcontractor` type structurally satisfies this (money/score fields stay
 * `number | string` so the raw record is assignable without a cast).
 */
interface SubcontractorLite {
  legal_name: string;
  trade_categories: string[];
  prequalification_status: string;
  rating_score: number | string;
  is_active: boolean;
  is_blocked?: boolean;
  insurance_expiry_date?: string | null;
  created_at: string;
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function statusLabel(code: string, t: Translate): string {
  return t(`subcontractors.insights.status_${code}`, {
    defaultValue: code.charAt(0).toUpperCase() + code.slice(1),
  });
}

/**
 * 3-state insurance bucket mirroring the register's own traffic-light
 * (`insuranceStatus` in SubcontractorsPage): valid > 30 days, expiring within
 * 30 days, or expired / missing. Missing is folded into the red bucket exactly
 * as the page does.
 */
function insuranceLabel(expiry: string | null | undefined, t: Translate): string {
  const expired = () =>
    t('subcontractors.insights.ins_expired', { defaultValue: 'Expired or missing' });
  if (!expiry) return expired();
  const exp = new Date(expiry);
  if (Number.isNaN(exp.getTime())) return expired();
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.floor((exp.getTime() - today.getTime()) / 86_400_000);
  if (diffDays < 0) return expired();
  if (diffDays <= 30)
    return t('subcontractors.insights.ins_soon', { defaultValue: 'Expiring soon' });
  return t('subcontractors.insights.ins_ok', { defaultValue: 'Insurance valid' });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  name: string;
  trade: string;
  status: string;
  insurance: string;
  month: string;
  rating: number;
  approved: number;
  active: number;
  blocked: number;
}

function toRow(s: SubcontractorLite, unassigned: string, t: Translate): Row {
  const primaryTrade = s.trade_categories?.[0]?.trim();
  return {
    name: s.legal_name ?? '',
    trade: primaryTrade || unassigned,
    status: statusLabel(s.prequalification_status, t),
    insurance: insuranceLabel(s.insurance_expiry_date, t),
    month: monthKey(s.created_at),
    rating: Number(s.rating_score) || 0,
    approved: s.prequalification_status === 'approved' ? 1 : 0,
    active: s.is_active ? 1 : 0,
    blocked: s.is_blocked ? 1 : 0,
  };
}

export interface SubcontractorsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildSubcontractorsInsights(
  subs: SubcontractorLite[],
  currency: string,
  t: Translate,
): SubcontractorsInsights {
  const unassigned = t('subcontractors.insights.trade_unassigned', { defaultValue: 'Unassigned' });

  const rows: Row[] = [...subs]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((s) => toRow(s, unassigned, t));

  const dataset: InsightDataset = {
    id: 'subcontractors',
    label: t('subcontractors.insights.ds_subcontractors', { defaultValue: 'Subcontractor register' }),
    currency: currency || '',
    fields: [
      { key: 'name', label: t('subcontractors.insights.f_name', { defaultValue: 'Name' }), kind: 'dimension' },
      { key: 'trade', label: t('subcontractors.insights.f_trade', { defaultValue: 'Trade' }), kind: 'dimension' },
      { key: 'status', label: t('subcontractors.insights.f_status', { defaultValue: 'Prequalification status' }), kind: 'dimension' },
      { key: 'insurance', label: t('subcontractors.insights.f_insurance', { defaultValue: 'Insurance' }), kind: 'dimension' },
      { key: 'month', label: t('subcontractors.insights.f_month', { defaultValue: 'Registered' }), kind: 'dimension' },
      { key: 'rating', label: t('subcontractors.insights.f_rating', { defaultValue: 'Rating' }), kind: 'measure', format: 'number' },
      { key: 'approved', label: t('subcontractors.insights.f_approved', { defaultValue: 'Approved' }), kind: 'measure', format: 'number' },
      { key: 'active', label: t('subcontractors.insights.f_active', { defaultValue: 'Active' }), kind: 'measure', format: 'number' },
      { key: 'blocked', label: t('subcontractors.insights.f_blocked', { defaultValue: 'Blocked' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'subcontractors', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-subs', title: t('subcontractors.insights.k_subs', { defaultValue: 'Subcontractors' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-approved', title: t('subcontractors.insights.k_approved', { defaultValue: 'Approved' }), chart: 'kpi', measure: 'approved', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-active', title: t('subcontractors.insights.k_active', { defaultValue: 'Active' }), chart: 'kpi', measure: 'active', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-avg-rating', title: t('subcontractors.insights.k_avgrating', { defaultValue: 'Avg rating' }), chart: 'kpi', measure: 'rating', agg: 'avg', color: 4 },
    { ...base, id: 'bar-by-trade', title: t('subcontractors.insights.c_by_trade', { defaultValue: 'Subcontractors by trade' }), chart: 'bar', dimension: 'trade', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('subcontractors.insights.c_by_status', { defaultValue: 'By prequalification status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-insurance', title: t('subcontractors.insights.c_by_insurance', { defaultValue: 'By insurance status' }), chart: 'bar', dimension: 'insurance', agg: 'count', color: 1 },
    { ...base, id: 'area-over-time', title: t('subcontractors.insights.c_over_time', { defaultValue: 'Registered over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
