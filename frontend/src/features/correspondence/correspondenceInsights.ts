// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Correspondence register's contribution to the Module Insights panel: it turns
 * the letters, notices, emails and memos the page already loaded into one
 * dataset plus a set of built-in KPIs and charts (by type, by status, incoming
 * vs outgoing, and how many entries land over time). When a project has no
 * correspondence yet, the panel simply stays empty until the register holds
 * records.
 *
 * Value labels reuse the same `correspondence.type_*` / `correspondence.status_*`
 * / `correspondence.dir_*` i18n keys the register uses, so a slice in a chart
 * reads exactly like the badge on the row it came from. Correspondence carries
 * no money field, so every measure is a plain number (a count, a day count or a
 * 0/1 flag) - there is no currency KPI.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

// Minimal shape this builder needs from a correspondence entry. The page hands
// it the full Correspondence[] (structurally a superset of this), so no mapping
// is needed at the call site.
interface CorrespondenceLite {
  subject: string;
  direction: string;
  correspondence_type: string;
  status: string;
  date_sent: string | null;
  date_received: string | null;
  is_overdue: boolean;
  created_at: string;
  updated_at: string;
}

// A record is done once it has been responded to or closed - nobody owes the
// next move and its age clock stops at the last update. open / awaiting_response
// are still live.
const DONE_STATUSES = ['responded', 'closed'];
const OPEN_STATUSES = ['open', 'awaiting_response'];

/** Parse an ISO date, anchoring bare yyyy-mm-dd values to local midnight so the
 *  month/age never drift a day for viewers west of UTC. Full timestamps already
 *  carry their own time. */
function parseTime(iso: string | null | undefined): number {
  if (!iso) return NaN;
  const s = iso.length === 10 ? `${iso}T00:00:00` : iso;
  return new Date(s).getTime();
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const ms = parseTime(iso);
  if (Number.isNaN(ms)) return 'n/a';
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Reasonable title-case fallback; the real translation wins when present. */
function humanize(code: string): string {
  const s = code.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function typeLabel(code: string, t: Translate): string {
  return t(`correspondence.type_${code}`, { defaultValue: humanize(code) });
}

function statusLabel(code: string, t: Translate): string {
  return t(`correspondence.status_${code}`, { defaultValue: humanize(code) });
}

function directionLabel(code: string, t: Translate): string {
  return t(`correspondence.dir_${code}`, {
    defaultValue: code === 'incoming' ? 'Incoming' : 'Outgoing',
  });
}

/** The entry's key date: when it was sent (outgoing) or received (incoming),
 *  falling back to when it was logged. */
function keyDate(r: CorrespondenceLite): string {
  const primary = r.direction === 'incoming' ? r.date_received : r.date_sent;
  return primary || r.created_at;
}

/** Whole days the entry has been (or was) live: key date -> now for a live one,
 *  key date -> last update for a done one. Never negative. */
function ageDays(r: CorrespondenceLite): number {
  const start = parseTime(keyDate(r));
  if (Number.isNaN(start)) return 0;
  const done = DONE_STATUSES.includes(r.status);
  const endRaw = done ? parseTime(r.updated_at) : Date.now();
  const end = Number.isNaN(endRaw) ? Date.now() : endRaw;
  return Math.max(0, Math.floor((end - start) / 86_400_000));
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  subject: string;
  type: string;
  status: string;
  direction: string;
  month: string;
  age: number;
  open: number;
  overdue: number;
  closed: number;
}

function toRow(r: CorrespondenceLite, t: Translate): Row {
  return {
    subject: r.subject ?? '',
    type: typeLabel(r.correspondence_type, t),
    status: statusLabel(r.status, t),
    direction: directionLabel(r.direction, t),
    month: monthKey(keyDate(r)),
    age: ageDays(r),
    open: OPEN_STATUSES.includes(r.status) ? 1 : 0,
    overdue: r.is_overdue ? 1 : 0,
    closed: r.status === 'closed' ? 1 : 0,
  };
}

export interface CorrespondenceInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildCorrespondenceInsights(
  items: CorrespondenceLite[],
  currency: string,
  t: Translate,
): CorrespondenceInsights {
  const rows: Row[] = [...items]
    .sort((a, b) => parseTime(keyDate(a)) - parseTime(keyDate(b)))
    .map((r) => toRow(r, t));

  const dataset: InsightDataset = {
    id: 'correspondence',
    label: t('correspondence.insights.ds_correspondence', { defaultValue: 'Correspondence register' }),
    currency: currency || '',
    fields: [
      { key: 'subject', label: t('correspondence.insights.f_subject', { defaultValue: 'Subject' }), kind: 'dimension' },
      { key: 'type', label: t('correspondence.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'status', label: t('correspondence.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'direction', label: t('correspondence.insights.f_direction', { defaultValue: 'Direction' }), kind: 'dimension' },
      { key: 'month', label: t('correspondence.insights.f_month', { defaultValue: 'Month' }), kind: 'dimension' },
      { key: 'age', label: t('correspondence.insights.f_age', { defaultValue: 'Age (days)' }), kind: 'measure', format: 'number' },
      { key: 'open', label: t('correspondence.insights.f_open', { defaultValue: 'Open' }), kind: 'measure', format: 'number' },
      { key: 'overdue', label: t('correspondence.insights.f_overdue', { defaultValue: 'Overdue' }), kind: 'measure', format: 'number' },
      { key: 'closed', label: t('correspondence.insights.f_closed', { defaultValue: 'Closed' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'correspondence', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-entries', title: t('correspondence.insights.k_entries', { defaultValue: 'Entries' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-open', title: t('correspondence.insights.k_open', { defaultValue: 'Open' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-overdue', title: t('correspondence.insights.k_overdue', { defaultValue: 'Overdue' }), chart: 'kpi', measure: 'overdue', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-avg-age', title: t('correspondence.insights.k_avg_age', { defaultValue: 'Avg age (days)' }), chart: 'kpi', measure: 'age', agg: 'avg', color: 4 },
    { ...base, id: 'bar-by-type', title: t('correspondence.insights.c_by_type', { defaultValue: 'Correspondence by type' }), chart: 'bar', dimension: 'type', agg: 'count', color: 0 },
    { ...base, id: 'donut-by-status', title: t('correspondence.insights.c_by_status', { defaultValue: 'Correspondence by status' }), chart: 'donut', dimension: 'status', agg: 'count', color: 4 },
    { ...base, id: 'bar-by-direction', title: t('correspondence.insights.c_by_direction', { defaultValue: 'Incoming vs outgoing' }), chart: 'bar', dimension: 'direction', agg: 'count', color: 3 },
    { ...base, id: 'area-over-time', title: t('correspondence.insights.c_over_time', { defaultValue: 'Correspondence logged over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [dataset], builtins };
}
