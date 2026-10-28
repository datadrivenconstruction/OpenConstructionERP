// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Bid Management's contribution to the Module Insights panel. It reads the bid
 * packages the page already loaded (the register on the default Packages tab,
 * where every package carries a budget estimate, a lifecycle status and a
 * confidentiality level) and turns them into one dataset plus built-in KPIs and
 * charts: package count, total budget, awarded and open counts, budget by
 * status, the confidentiality split, and how budget and package count build up
 * over time. The panel stays empty until the project holds bid packages.
 *
 * The panel charts packages specifically (not the bids inside them): packages
 * are the flat register the page loads at the top level, and each row already
 * shows a budget and a status the table colours, so a chart slice reads exactly
 * like the badge on the row it came from. Labels reuse the same
 * `bid_management.status_*` and `bid_management.confidentiality_*` i18n keys the
 * package table uses.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shape the builder needs from a bid package. The module's `BidPackage`
 * type structurally satisfies this (the money field stays `number | string` so
 * the raw record is assignable without a cast).
 */
interface PackageLite {
  title?: string;
  code?: string;
  status?: string;
  confidentiality_level?: string;
  total_budget_estimate?: number | string;
  currency?: string;
  created_at?: string;
}

// Statuses that mean the package has been won/committed vs is still live and
// accepting bids - used for the two derived 0/1 flag measures.
const AWARDED_STATUS = 'awarded';
const OPEN_STATUS = 'open';

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

// Human labels for the package status enum, kept as the t() defaultValue so
// English reads well before the locale keys land. Mirrors the page's own
// PACKAGE_STATUS_LABEL_FALLBACK so a chart slice matches the status badge.
const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  published: 'Published',
  open: 'Open',
  closed: 'Closed',
  cancelled: 'Cancelled',
  awarded: 'Awarded',
};

const CONFIDENTIALITY_LABELS: Record<string, string> = {
  public: 'Public',
  limited: 'Limited',
  confidential: 'Confidential',
};

/** Fallback for an unknown code: "under_review" -> "Under review". */
function humanize(code: string): string {
  const spaced = code.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : spaced;
}

/** Reuse the package table's `bid_management.status_*` keys so a chart slice
 *  reads exactly like the status badge on the row it came from. */
function statusLabel(code: string, t: Translate): string {
  return t(`bid_management.status_${code}`, { defaultValue: STATUS_LABELS[code] ?? humanize(code) });
}

/** Reuse the package table's `bid_management.confidentiality_*` keys. */
function confidentialityLabel(code: string, t: Translate): string {
  return t(`bid_management.confidentiality_${code}`, {
    defaultValue: CONFIDENTIALITY_LABELS[code] ?? humanize(code),
  });
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  status: string;
  confidentiality: string;
  month: string;
  budget: number;
  awarded: number;
  open: number;
}

function toRow(pkg: PackageLite, untitled: string, t: Translate): Row {
  const status = pkg.status ?? '';
  return {
    title: pkg.title?.trim() || pkg.code || untitled,
    status: statusLabel(status, t),
    confidentiality: confidentialityLabel(pkg.confidentiality_level ?? 'public', t),
    month: monthKey(pkg.created_at ?? ''),
    budget: Number(pkg.total_budget_estimate) || 0,
    awarded: status === AWARDED_STATUS ? 1 : 0,
    open: status === OPEN_STATUS ? 1 : 0,
  };
}

export interface BidManagementInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildBidManagementInsights(
  packages: PackageLite[],
  currency: string,
  t: Translate,
): BidManagementInsights {
  const untitled = t('bid_management.insights.untitled', { defaultValue: 'Untitled package' });

  const dateOf = (p: PackageLite): number => new Date(p.created_at ?? '').getTime();

  const rows: Row[] = [...packages]
    .sort((a, b) => (dateOf(a) || 0) - (dateOf(b) || 0))
    .map((p) => toRow(p, untitled, t));

  const dataset: InsightDataset = {
    id: 'packages',
    label: t('bid_management.insights.ds_packages', { defaultValue: 'Bid packages' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('bid_management.insights.f_title', { defaultValue: 'Package' }), kind: 'dimension' },
      { key: 'status', label: t('bid_management.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'confidentiality', label: t('bid_management.insights.f_confidentiality', { defaultValue: 'Confidentiality' }), kind: 'dimension' },
      { key: 'month', label: t('bid_management.insights.f_month', { defaultValue: 'Month created' }), kind: 'dimension' },
      { key: 'budget', label: t('bid_management.insights.f_budget', { defaultValue: 'Budget estimate' }), kind: 'measure', format: 'currency' },
      { key: 'awarded', label: t('bid_management.insights.f_awarded', { defaultValue: 'Awarded' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('bid_management.insights.f_open', { defaultValue: 'Open for bids' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'packages', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-count', title: t('bid_management.insights.k_count', { defaultValue: 'Packages' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-budget', title: t('bid_management.insights.k_budget', { defaultValue: 'Total budget' }), chart: 'kpi', measure: 'budget', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-awarded', title: t('bid_management.insights.k_awarded', { defaultValue: 'Awarded' }), chart: 'kpi', measure: 'awarded', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-open', title: t('bid_management.insights.k_open', { defaultValue: 'Open for bids' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 4 },
    { ...base, id: 'bar-budget-by-status', title: t('bid_management.insights.c_budget_by_status', { defaultValue: 'Budget by status' }), chart: 'bar', dimension: 'status', measure: 'budget', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-confidentiality', title: t('bid_management.insights.c_by_confidentiality', { defaultValue: 'Packages by confidentiality' }), chart: 'donut', dimension: 'confidentiality', agg: 'count', color: 4 },
    { ...base, id: 'line-budget-over-time', title: t('bid_management.insights.c_budget_over_time', { defaultValue: 'Budget over time' }), chart: 'line', dimension: 'month', measure: 'budget', agg: 'sum', color: 5 },
    { ...base, id: 'area-over-time', title: t('bid_management.insights.c_over_time', { defaultValue: 'Packages over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 3 },
  ];

  return { datasets: [dataset], builtins };
}
