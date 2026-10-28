// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tendering's contribution to the Module Insights panel: it turns the tender
 * packages the page already loaded into one dataset plus a set of built-in
 * KPIs and charts. When a project has no packages yet, the panel simply stays
 * empty until the module holds records.
 *
 * This is the template every other module follows: expose a dataset (rows +
 * typed fields) and a few built-in definitions, and the shared panel does the
 * rest, including letting the user build their own charts from the same fields.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

interface PackageLite {
  status: string;
  bid_count: number;
  created_at: string;
  name: string;
}

const OPEN_STATUSES = ['issued', 'collecting', 'evaluating'];

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function statusLabel(code: string, t: Translate): string {
  const key = `tendering.status_${code}`;
  return t(key, { defaultValue: code.charAt(0).toUpperCase() + code.slice(1) });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  name: string;
  status: string;
  month: string;
  bids: number;
  awarded: number;
  open: number;
}

function toRow(name: string, code: string, month: string, bids: number, t: Translate): Row {
  return {
    name,
    status: statusLabel(code, t),
    month,
    bids,
    awarded: code === 'awarded' ? 1 : 0,
    open: OPEN_STATUSES.includes(code) ? 1 : 0,
  };
}

export interface TenderingInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildTenderingInsights(
  packages: PackageLite[],
  currency: string,
  t: Translate,
): TenderingInsights {
  const rows: Row[] = [...packages]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((p) => toRow(p.name, p.status, monthKey(p.created_at), p.bid_count ?? 0, t));

  const dataset: InsightDataset = {
    id: 'packages',
    label: t('tendering.insights.ds_packages', { defaultValue: 'Tender packages' }),
    currency: currency || '',
    fields: [
      { key: 'name', label: t('tendering.insights.f_name', { defaultValue: 'Package' }), kind: 'dimension' },
      { key: 'status', label: t('tendering.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'month', label: t('tendering.insights.f_month', { defaultValue: 'Month created' }), kind: 'dimension' },
      { key: 'bids', label: t('tendering.insights.f_bids', { defaultValue: 'Bids' }), kind: 'measure', format: 'number' },
      { key: 'awarded', label: t('tendering.insights.f_awarded', { defaultValue: 'Awarded' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('tendering.insights.f_open', { defaultValue: 'Open tenders' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'packages', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-packages', title: t('tendering.insights.k_packages', { defaultValue: 'Packages' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-bids', title: t('tendering.insights.k_bids', { defaultValue: 'Bids received' }), chart: 'kpi', measure: 'bids', agg: 'sum', color: 5 },
    { ...base, id: 'kpi-avg-bids', title: t('tendering.insights.k_avgbids', { defaultValue: 'Avg bids / package' }), chart: 'kpi', measure: 'bids', agg: 'avg', color: 2 },
    { ...base, id: 'kpi-awarded', title: t('tendering.insights.k_awarded', { defaultValue: 'Awarded' }), chart: 'kpi', measure: 'awarded', agg: 'sum', color: 1 },
    { ...base, id: 'bar-bids-by-pkg', title: t('tendering.insights.c_bids_by_pkg', { defaultValue: 'Bids by package' }), chart: 'bar', dimension: 'name', measure: 'bids', agg: 'sum', color: 0 },
    { ...base, id: 'donut-by-status', title: t('tendering.insights.c_by_status', { defaultValue: 'Packages by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 2 },
    { ...base, id: 'area-over-time', title: t('tendering.insights.c_over_time', { defaultValue: 'Tenders created over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
