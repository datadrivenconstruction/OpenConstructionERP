// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Approvals register's contribution to the Module Insights panel.
 *
 * The register answers "what is in review". What it cannot answer, and what
 * actually unblocks a job, is who the queue is sitting with and how long
 * things take once they are submitted. A drawing that has been with the same
 * approver for three weeks is a programme risk, not a row in a table.
 *
 * So the panel groups outstanding work by the approver whose decision is next
 * (the same "ball in court" the register's Current step column derives) and
 * puts turnaround time against file type.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { ApprovalWorkflow } from './types';

type Translate = ReturnType<typeof useTranslation>['t'];

const DAY_MS = 24 * 60 * 60 * 1000;

function titleCase(code: string): string {
  return code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, ' ');
}

/** Same key the register's status badge uses, so a slice reads like a badge. */
function statusLabel(code: string, t: Translate): string {
  return t(`files.approvals.status.${code}`, { defaultValue: titleCase(code) });
}

function kindLabel(code: string, t: Translate): string {
  return t(`files.approvals.kind_${code}`, { defaultValue: titleCase(code) });
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/**
 * Whoever the workflow is waiting on: the first step still pending, by sort
 * order. Derived exactly as the register's Current step column derives it, so
 * a bar in the chart and a cell in the table never disagree.
 */
function ballInCourt(w: ApprovalWorkflow, settled: string): string {
  const pending = [...(w.steps ?? [])]
    .sort((a, b) => a.sort_order - b.sort_order)
    .find((s) => s.decision === 'pending');
  if (!pending) return settled;
  return pending.role_label?.trim() || pending.approver_id.slice(0, 8);
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  file: string;
  kind: string;
  status: string;
  approver: string;
  month: string;
  open: number;
  rejected: number;
  days: number;
  steps: number;
}

function toRow(w: ApprovalWorkflow, settled: string, t: Translate): Row {
  const inReview = w.status === 'in_review';
  const submitted = new Date(w.submitted_at).getTime();
  // Turnaround runs to the decision for settled workflows and to now for the
  // ones still open, so an open item's number keeps growing until it is dealt
  // with. That is the point: a stale submission should look worse each week.
  const decidedAt = w.final_decision_at ? new Date(w.final_decision_at).getTime() : NaN;
  const end = !inReview && !Number.isNaN(decidedAt) ? decidedAt : Date.now();

  return {
    file: w.file_id ?? '',
    kind: kindLabel(String(w.file_kind), t),
    status: statusLabel(String(w.status), t),
    approver: inReview ? ballInCourt(w, settled) : settled,
    month: monthKey(w.submitted_at),
    open: inReview ? 1 : 0,
    rejected: w.status === 'rejected' ? 1 : 0,
    days: Number.isNaN(submitted) ? 0 : Math.max(0, Math.floor((end - submitted) / DAY_MS)),
    steps: w.steps?.length ?? 0,
  };
}

export interface FileApprovalsInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/**
 * Build the approvals dataset and its built-in charts. An approval workflow
 * carries no money, so there is no currency-formatted measure.
 */
export function buildFileApprovalsInsights(
  workflows: ApprovalWorkflow[],
  t: Translate,
): FileApprovalsInsights {
  const settled = t('files.approvals.insights.settled', { defaultValue: 'Decided' });

  const rows: Row[] = [...workflows]
    .sort((a, b) => new Date(a.submitted_at).getTime() - new Date(b.submitted_at).getTime())
    .map((w) => toRow(w, settled, t));

  const dataset: InsightDataset = {
    id: 'approvals',
    label: t('files.approvals.insights.ds_approvals', { defaultValue: 'Approvals register' }),
    currency: '',
    fields: [
      { key: 'file', label: t('files.approvals.insights.f_file', { defaultValue: 'File' }), kind: 'dimension' },
      { key: 'kind', label: t('files.approvals.insights.f_kind', { defaultValue: 'File type' }), kind: 'dimension' },
      { key: 'status', label: t('files.approvals.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'approver', label: t('files.approvals.insights.f_approver', { defaultValue: 'Waiting on' }), kind: 'dimension' },
      { key: 'month', label: t('files.approvals.insights.f_month', { defaultValue: 'Month submitted' }), kind: 'dimension' },
      { key: 'open', label: t('files.approvals.insights.f_open', { defaultValue: 'Still in review' }), kind: 'measure', format: 'number' },
      { key: 'rejected', label: t('files.approvals.insights.f_rejected', { defaultValue: 'Rejected' }), kind: 'measure', format: 'number' },
      { key: 'days', label: t('files.approvals.insights.f_days', { defaultValue: 'Days in review' }), kind: 'measure', format: 'number' },
      { key: 'steps', label: t('files.approvals.insights.f_steps', { defaultValue: 'Approval steps' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'approvals', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-submissions', title: t('files.approvals.insights.k_submissions', { defaultValue: 'Submissions' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('files.approvals.insights.k_open', { defaultValue: 'Awaiting a decision' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-days', title: t('files.approvals.insights.k_days', { defaultValue: 'Avg days in review' }), chart: 'kpi', measure: 'days', agg: 'avg', color: 5 },
    { ...base, id: 'kpi-rejected', title: t('files.approvals.insights.k_rejected', { defaultValue: 'Rejected' }), chart: 'kpi', measure: 'rejected', agg: 'sum', color: 1 },
    { ...base, id: 'bar-open-by-approver', title: t('files.approvals.insights.c_open_by_approver', { defaultValue: 'Waiting on which approver' }), chart: 'bar', dimension: 'approver', measure: 'open', agg: 'sum', color: 1 },
    { ...base, id: 'bar-days-by-kind', title: t('files.approvals.insights.c_days_by_kind', { defaultValue: 'Average days in review by file type' }), chart: 'bar', dimension: 'kind', measure: 'days', agg: 'avg', color: 5 },
    { ...base, id: 'donut-by-status', title: t('files.approvals.insights.c_by_status', { defaultValue: 'Submissions by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 0 },
    { ...base, id: 'area-over-time', title: t('files.approvals.insights.c_over_time', { defaultValue: 'Submissions over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 4 },
  ];

  return { datasets: [dataset], builtins };
}
