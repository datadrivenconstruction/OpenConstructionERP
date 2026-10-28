// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Review Authority's contribution to the Module Insights panel.
 *
 * The list answers "which cycles are open". What it cannot answer, and what
 * decides whether a programme holds, is which authority is sitting on our
 * submissions and how long that body actually takes. An authority that
 * averages six weeks is a planning input; the same authority overdue on three
 * live cycles is an escalation today.
 *
 * Rows are the cycles the page already loaded. Remarks deliberately are NOT
 * used: they are fetched per cycle inside CycleDetailPanel, so a remark-level
 * dataset would need a query the page does not make. Cycle level is what is
 * honestly available here.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { ReviewCycle } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

const DAY_MS = 24 * 60 * 60 * 1000;

/** Cycles that have reached a final decision and are no longer chaseable. */
const SETTLED_STATUSES = ['approved', 'rejected', 'withdrawn'];

function titleCase(code: string): string {
  return code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, ' ');
}

/** Same keys the list row's badges use, so a slice reads like a badge. */
function statusLabel(code: string, t: Translate): string {
  return t(`review_authority.cycle_status_${code}`, { defaultValue: titleCase(code) });
}

function kindLabel(code: string, t: Translate): string {
  return t(`review_authority.authority_kind_${code}`, { defaultValue: titleCase(code) });
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  submission: string;
  authority: string;
  kind: string;
  status: string;
  jurisdiction: string;
  opened_month: string;
  open: number;
  overdue: number;
  days_late: number;
  days_open: number;
  drift: number;
}

function toRow(c: ReviewCycle, noJurisdiction: string, t: Translate): Row {
  const settled = SETTLED_STATUSES.includes(c.status);
  const opened = c.opened_at ? new Date(c.opened_at).getTime() : NaN;
  // A settled cycle stops ageing at its last update; a live one keeps ageing,
  // so a submission nobody has touched looks worse every week.
  const end = settled ? new Date(c.updated_at).getTime() : Date.now();

  return {
    submission: c.submission_ref?.trim() || c.id.slice(0, 8),
    authority: c.authority_name?.trim() || kindLabel(String(c.authority_kind), t),
    kind: kindLabel(String(c.authority_kind), t),
    status: statusLabel(String(c.status), t),
    jurisdiction: c.jurisdiction?.trim() || noJurisdiction,
    opened_month: monthKey(c.opened_at),
    open: settled ? 0 : 1,
    overdue: c.overdue ? 1 : 0,
    // days_remaining goes negative once overdue. Only genuinely late work
    // carries a slip, otherwise a cycle due next month would pull the average
    // down and make the authority look faster than it is.
    days_late: c.overdue && c.days_remaining !== null ? Math.max(0, -c.days_remaining) : 0,
    days_open:
      Number.isNaN(opened) || Number.isNaN(end) ? 0 : Math.max(0, Math.floor((end - opened) / DAY_MS)),
    // The authority is reviewing a document the project has already moved past,
    // so any remark it raises is answering an outdated drawing. Quiet, costly,
    // and invisible in the list.
    drift:
      c.pinned_document_version && c.pinned_document_version !== c.current_document_version ? 1 : 0,
  };
}

export interface ReviewAuthorityInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/**
 * Build the review cycle dataset and its built-in charts. A review cycle
 * carries no money, so there is no currency-formatted measure.
 */
export function buildReviewAuthorityInsights(
  cycles: ReviewCycle[],
  t: Translate,
): ReviewAuthorityInsights {
  const noJurisdiction = t('review_authority.insights.no_jurisdiction', {
    defaultValue: 'No jurisdiction set',
  });

  const rows: Row[] = cycles.map((c) => toRow(c, noJurisdiction, t));

  const dataset: InsightDataset = {
    id: 'cycles',
    label: t('review_authority.insights.ds_cycles', { defaultValue: 'Review cycles' }),
    currency: '',
    fields: [
      { key: 'submission', label: t('review_authority.insights.f_submission', { defaultValue: 'Submission' }), kind: 'dimension' },
      { key: 'authority', label: t('review_authority.insights.f_authority', { defaultValue: 'Authority' }), kind: 'dimension' },
      { key: 'kind', label: t('review_authority.insights.f_kind', { defaultValue: 'Authority type' }), kind: 'dimension' },
      { key: 'status', label: t('review_authority.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'jurisdiction', label: t('review_authority.insights.f_jurisdiction', { defaultValue: 'Jurisdiction' }), kind: 'dimension' },
      { key: 'opened_month', label: t('review_authority.insights.f_opened_month', { defaultValue: 'Month opened' }), kind: 'dimension' },
      { key: 'open', label: t('review_authority.insights.f_open', { defaultValue: 'Still open' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('review_authority.insights.f_overdue', { defaultValue: 'Past the SLA date' }), kind: 'measure', format: 'number' },
      { key: 'days_late', label: t('review_authority.insights.f_days_late', { defaultValue: 'Days past the SLA date' }), kind: 'measure', format: 'number' },
      { key: 'days_open', label: t('review_authority.insights.f_days_open', { defaultValue: 'Days with the authority' }), kind: 'measure', format: 'number' },
      { key: 'drift', label: t('review_authority.insights.f_drift', { defaultValue: 'Reviewing an outdated version' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'cycles', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-cycles', title: t('review_authority.insights.k_cycles', { defaultValue: 'Review cycles' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('review_authority.insights.k_open', { defaultValue: 'Still with an authority' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-overdue', title: t('review_authority.insights.k_overdue', { defaultValue: 'Past the SLA date' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-drift', title: t('review_authority.insights.k_drift', { defaultValue: 'Reviewing an outdated version' }), chart: 'kpi', measure: 'drift', agg: 'sum', color: 5 },
    { ...base, id: 'bar-overdue-by-authority', title: t('review_authority.insights.c_overdue_by_authority', { defaultValue: 'Overdue by authority' }), chart: 'bar', dimension: 'authority', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'bar-days-by-kind', title: t('review_authority.insights.c_days_by_kind', { defaultValue: 'Average days with each authority type' }), chart: 'bar', dimension: 'kind', measure: 'days_open', agg: 'avg', color: 5 },
    { ...base, id: 'donut-by-status', title: t('review_authority.insights.c_by_status', { defaultValue: 'Cycles by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 0 },
    { ...base, id: 'area-over-time', title: t('review_authority.insights.c_over_time', { defaultValue: 'Cycles opened over time' }), chart: 'area', dimension: 'opened_month', agg: 'count', color: 4 },
  ];

  return { datasets: [dataset], builtins };
}
