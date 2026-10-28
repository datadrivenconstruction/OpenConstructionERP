// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Punch list's contribution to the Module Insights panel. The snag table shows
 * one row per defect; what a site manager actually needs before a walk is the
 * shape of the list - which trade is carrying the most open work, how much of
 * it is past its due date, and whether the list is shrinking or growing week
 * on week. Those are exactly the numbers a row-by-row table hides.
 *
 * Everything is derived from the punch items the page already loaded, so the
 * panel costs no extra request. On a project with no snags there is nothing to
 * draw, and the panel stays empty rather than inventing a list.
 *
 * Row VALUES reuse the same `punch.status_*` / `punch.priority_*` /
 * `punch.category_*` keys the table badges use, so a chart slice reads exactly
 * like the badge on the row it came from.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { PunchItem } from './api';
import { resolveAssignee } from './assignee';
import { parseDateUTC } from '@/shared/lib/dates';

type Translate = ReturnType<typeof useTranslation>['t'];

/** Statuses that mean the snag is off the site manager's list. */
const DONE_STATUSES = ['resolved', 'verified', 'closed'];

const DAY_MS = 24 * 60 * 60 * 1000;

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function titleCase(code: string): string {
  return code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, ' ');
}

function statusLabel(code: string, t: Translate): string {
  return t(`punch.status_${code}`, { defaultValue: titleCase(code) });
}

function priorityLabel(code: string, t: Translate): string {
  return t(`punch.priority_${code}`, { defaultValue: titleCase(code) });
}

function categoryLabel(code: string | null, t: Translate, fallback: string): string {
  if (!code) return fallback;
  return t(`punch.category_${code}`, { defaultValue: titleCase(code) });
}

/**
 * Whole days between two instants, floored at zero. Used for both "how long
 * has this been open" and "how far past its due date is it".
 */
function daysBetween(fromIso: string, toMs: number): number {
  const from = new Date(fromIso).getTime();
  if (Number.isNaN(from)) return 0;
  return Math.max(0, Math.floor((toMs - from) / DAY_MS));
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  title: string;
  status: string;
  priority: string;
  category: string;
  trade: string;
  assignee: string;
  month: string;
  open: number;
  overdue: number;
  age: number;
  reopened: number;
}

/**
 * Which bar a snag belongs on when the chart groups by assignee.
 *
 * The column can hold a contact id, and an id makes a bar nobody can read.
 * Ids the API resolved group under the person; ids it could not resolve get
 * their own bucket rather than joining the genuinely unassigned work, which
 * is a different queue with a different owner.
 */
function assigneeBucket(item: PunchItem, unassigned: string, unknown: string): string {
  const who = resolveAssignee(item.assigned_to, item.assigned_to_name);
  if (who.kind === 'named') return who.name;
  return who.kind === 'unresolved' ? unknown : unassigned;
}

function toRow(
  item: PunchItem,
  unassigned: string,
  none: string,
  unknown: string,
  t: Translate,
): Row {
  const now = Date.now();
  const isOpen = !DONE_STATUSES.includes(item.status);
  const due = item.due_date ? parseDateUTC(item.due_date).getTime() : NaN;
  // "Overdue" only counts work still outstanding. A snag closed late is a
  // historical fact, not something to chase today.
  const overdue = isOpen && !Number.isNaN(due) && due < now ? 1 : 0;
  // Age runs to the point the snag left the list, so closed items keep the
  // turnaround they actually had rather than ageing forever.
  const end = !isOpen && item.resolved_at ? new Date(item.resolved_at).getTime() : now;

  return {
    title: item.title ?? '',
    status: statusLabel(item.status, t),
    priority: priorityLabel(item.priority, t),
    category: categoryLabel(item.category, t, none),
    trade: item.trade?.trim() || none,
    assignee: assigneeBucket(item, unassigned, unknown),
    month: monthKey(item.created_at),
    open: isOpen ? 1 : 0,
    overdue,
    age: daysBetween(item.created_at, Number.isNaN(end) ? now : end),
    reopened: item.reopen_history?.length ?? 0,
  };
}

export interface PunchlistInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/**
 * Build the punch list dataset and its built-in charts.
 *
 * No `currency` argument and no currency-formatted measure. A punch item does
 * carry money now - `rework_cost` with its own `rework_cost_currency` - but a
 * page of items can hold several currencies, and adding those into one tile
 * would be a fake KPI, which is worse than none. A value of open items
 * belongs here only once it is summed per currency, the way the QMS cost of
 * poor quality and the retainage withholding already do it.
 */
export function buildPunchlistInsights(items: PunchItem[], t: Translate): PunchlistInsights {
  const unassigned = t('punch.insights.unassigned', { defaultValue: 'Unassigned' });
  const none = t('punch.insights.none', { defaultValue: 'Not set' });
  const unknown = t('common.unknown', { defaultValue: 'Unknown' });

  const rows: Row[] = [...items]
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((item) => toRow(item, unassigned, none, unknown, t));

  const dataset: InsightDataset = {
    id: 'punch',
    label: t('punch.insights.ds_punch', { defaultValue: 'Punch list' }),
    currency: '',
    fields: [
      { key: 'title', label: t('punch.insights.f_title', { defaultValue: 'Item' }), kind: 'dimension' },
      { key: 'status', label: t('punch.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'priority', label: t('punch.insights.f_priority', { defaultValue: 'Priority' }), kind: 'dimension' },
      { key: 'category', label: t('punch.insights.f_category', { defaultValue: 'Category' }), kind: 'dimension' },
      { key: 'trade', label: t('punch.insights.f_trade', { defaultValue: 'Trade' }), kind: 'dimension' },
      { key: 'assignee', label: t('punch.insights.f_assignee', { defaultValue: 'Assigned to' }), kind: 'dimension' },
      { key: 'month', label: t('punch.insights.f_month', { defaultValue: 'Month raised' }), kind: 'dimension' },
      { key: 'open', label: t('punch.insights.f_open', { defaultValue: 'Still open' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('punch.insights.f_overdue', { defaultValue: 'Overdue' }), kind: 'measure', format: 'number' },
      { key: 'age', label: t('punch.insights.f_age', { defaultValue: 'Days on the list' }), kind: 'measure', format: 'number' },
      { key: 'reopened', label: t('punch.insights.f_reopened', { defaultValue: 'Times reopened' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'punch', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-items', title: t('punch.insights.k_items', { defaultValue: 'Punch items' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('punch.insights.k_open', { defaultValue: 'Still open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 4 },
    { ...base, id: 'kpi-overdue', title: t('punch.insights.k_overdue', { defaultValue: 'Past due date' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-age', title: t('punch.insights.k_age', { defaultValue: 'Avg days on the list' }), chart: 'kpi', measure: 'age', agg: 'avg', color: 5 },
    { ...base, id: 'bar-open-by-trade', title: t('punch.insights.c_open_by_trade', { defaultValue: 'Open items by trade' }), chart: 'bar', dimension: 'trade', measure: 'open', agg: 'sum', color: 0 },
    { ...base, id: 'donut-by-status', title: t('punch.insights.c_by_status', { defaultValue: 'Items by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-overdue-by-priority', title: t('punch.insights.c_overdue_by_priority', { defaultValue: 'Overdue by priority' }), chart: 'bar', dimension: 'priority', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'area-over-time', title: t('punch.insights.c_over_time', { defaultValue: 'Items raised over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
