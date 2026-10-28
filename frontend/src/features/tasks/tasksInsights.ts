// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tasks register's contribution to the Module Insights panel: it turns the
 * tasks the page already loaded into one dataset plus a set of built-in KPIs
 * and charts (tasks by status, priority and type, and how many are created
 * over time). When a project has no tasks yet the dataset is empty and the
 * panel shows nothing, which is the honest answer for an empty register.
 *
 * Value labels reuse the same `tasks.status_*` / `tasks.priority_*` /
 * `tasks.type_*` i18n keys the board and badges use, so a slice in a chart
 * reads exactly like the badge on the card it came from. These are count /
 * age / status insights: a task carries no money field, so every measure is a
 * plain number (a count, a day count or a 0/1 flag) and there is no currency KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import { parseDateUTC } from '@/shared/lib/dates';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from a task. The page hands it the full
// Task[] (structurally a superset of this), so no mapping is needed at the
// call site.
interface TaskLite {
  title: string;
  status: string;
  task_type: string;
  priority: string;
  assigned_to_name: string | null;
  due_date: string | null;
  created_at: string;
  completed_at?: string | null;
  // Server-computed authoritative overdue flag (status != completed AND due
  // date strictly before today). Optional here so a caller holding a record
  // without it still gets a due-date compare rather than a type error.
  is_overdue?: boolean;
  metadata?: Record<string, unknown>;
}

const DONE_STATUS = 'completed';

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Title-case a snake_case code as a readable fallback (in_progress -> In
 *  Progress); the real translation wins when present. */
function humanize(code: string): string {
  return code
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function statusLabel(code: string, t: Translate): string {
  return t(`tasks.status_${code}`, { defaultValue: humanize(code) });
}

function priorityLabel(code: string, t: Translate): string {
  return t(`tasks.priority_${code}`, { defaultValue: humanize(code) });
}

function typeLabel(code: string, t: Translate): string {
  return t(`tasks.type_${code}`, { defaultValue: humanize(code) });
}

/** Whole days the task has been (or was) open: created -> now for an open one,
 *  created -> completion for a done one. Never negative. */
function daysOpen(r: TaskLite): number {
  const start = new Date(r.created_at).getTime();
  if (Number.isNaN(start)) return 0;
  const done = r.status === DONE_STATUS;
  const endRaw = done && r.completed_at ? new Date(r.completed_at).getTime() : Date.now();
  const end = Number.isNaN(endRaw) ? Date.now() : endRaw;
  return Math.max(0, Math.floor((end - start) / 86_400_000));
}

/** Not done and past due. Honours the server-computed is_overdue when present
 *  (the codebase warns against recomputing it client-side); falls back to a
 *  due-date compare for a row that carries no flag. */
function isOverdue(r: TaskLite, done: boolean): boolean {
  if (done) return false;
  if (typeof r.is_overdue === 'boolean') return r.is_overdue;
  if (!r.due_date) return false;
  const due = parseDateUTC(r.due_date).getTime();
  return !Number.isNaN(due) && due < Date.now();
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  status: string;
  priority: string;
  type: string;
  assignee: string;
  month: string;
  open: number;
  overdue: number;
  done: number;
  age: number;
}

function toRow(r: TaskLite, unassigned: string, t: Translate): Row {
  const done = r.status === DONE_STATUS;
  const metaName =
    r.metadata && typeof r.metadata.assignee_name === 'string'
      ? (r.metadata.assignee_name as string)
      : '';
  return {
    title: r.title ?? '',
    status: statusLabel(r.status, t),
    priority: priorityLabel(r.priority, t),
    type: typeLabel(r.task_type, t),
    assignee: r.assigned_to_name?.trim() || metaName.trim() || unassigned,
    month: monthKey(r.created_at),
    open: done ? 0 : 1,
    overdue: isOverdue(r, done) ? 1 : 0,
    done: done ? 1 : 0,
    age: daysOpen(r),
  };
}

export interface TasksInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildTasksInsights(
  tasks: TaskLite[],
  currency: string,
  t: Translate,
): TasksInsights {
  const unassigned = t('tasks.insights.unassigned', { defaultValue: 'Unassigned' });

  const rows: Row[] = [...tasks]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((r) => toRow(r, unassigned, t));

  const dataset: InsightDataset = {
    id: 'tasks',
    label: t('tasks.insights.ds_tasks', { defaultValue: 'Task register' }),
    currency: currency || '',
    fields: [
      { key: 'title', label: t('tasks.insights.f_title', { defaultValue: 'Task' }), kind: 'dimension' },
      { key: 'status', label: t('tasks.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'priority', label: t('tasks.insights.f_priority', { defaultValue: 'Priority' }), kind: 'dimension' },
      { key: 'type', label: t('tasks.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'assignee', label: t('tasks.insights.f_assignee', { defaultValue: 'Assignee' }), kind: 'dimension' },
      { key: 'month', label: t('tasks.insights.f_month', { defaultValue: 'Month created' }), kind: 'dimension' },
      { key: 'open', label: t('tasks.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('tasks.insights.f_overdue', { defaultValue: 'Overdue' }), kind: 'measure', format: 'number' },
      { key: 'done', label: t('tasks.insights.f_done', { defaultValue: 'Completed' }), kind: 'measure', format: 'number' },
      { key: 'age', label: t('tasks.insights.f_age', { defaultValue: 'Days open' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'tasks', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-tasks', title: t('tasks.insights.k_tasks', { defaultValue: 'Tasks' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('tasks.insights.k_open', { defaultValue: 'Open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-overdue', title: t('tasks.insights.k_overdue', { defaultValue: 'Overdue' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-done', title: t('tasks.insights.k_done', { defaultValue: 'Completed' }), chart: 'kpi', measure: 'done', agg: 'sum', color: 3 },
    { ...base, id: 'kpi-avg-age', title: t('tasks.insights.k_avg_age', { defaultValue: 'Avg days open' }), chart: 'kpi', measure: 'age', agg: 'avg', color: 4 },
    { ...base, id: 'donut-by-status', title: t('tasks.insights.c_by_status', { defaultValue: 'Tasks by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-priority', title: t('tasks.insights.c_by_priority', { defaultValue: 'Tasks by priority' }), chart: 'bar', dimension: 'priority', agg: 'count', color: 1 },
    { ...base, id: 'bar-by-type', title: t('tasks.insights.c_by_type', { defaultValue: 'Tasks by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'area-over-time', title: t('tasks.insights.c_over_time', { defaultValue: 'Tasks created over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
