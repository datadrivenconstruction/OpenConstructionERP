// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Service desk's contribution to the Module Insights panel.
 *
 * The tickets tab is a filterable table and nothing else: there is no summary
 * anywhere on the page, so every number here is new rather than a restatement.
 *
 * Two questions drive it. The first is the SLA, which the table already answers
 * one row at a time through its countdown chip but never in aggregate, so
 * nobody can see whether breaches cluster on critical tickets or on the low
 * priority ones nobody picks up. The second is the split between planned
 * maintenance and reactive callouts, which is the number a maintenance contract
 * actually lives or dies on and which appears nowhere in the UI today. Tickets
 * raised from a recurring schedule are planned; everything else is somebody
 * ringing up because something broke. A contract drifting towards reactive is
 * losing money long before anyone reads a cost report.
 *
 * Deliberately no money. Contracts and work orders both carry a value and a
 * currency, and mixing per-ticket counts with contract values would produce a
 * tile that looks like revenue and is not: the tickets in view are a filtered
 * slice, and their contracts overlap. Counts and hours are things this dataset
 * can honestly measure on its own.
 *
 * Breach is derived exactly the way the table's chip derives it, so a bar and a
 * chip never disagree: an explicit `sla_breached_at` always counts, and a past
 * `sla_due_at` counts only while the ticket is still live. A ticket that was
 * resolved late without the backend stamping the breach is not counted here,
 * for the same reason it shows no red chip in the table.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';
import type { ServiceTicket } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

const HOUR_MS = 60 * 60 * 1000;

/** Statuses the table treats as finished, so an SLA can no longer be missed. */
const TERMINAL = ['resolved', 'closed', 'cancelled'];

function titleCase(code: string): string {
  return code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, ' ');
}

/** Same keys the table's badges use, so a slice reads like a badge. */
function statusLabel(code: string, t: Translate): string {
  return t(`service.ticket_status_${code}`, { defaultValue: titleCase(code) });
}

function priorityLabel(code: string, t: Translate): string {
  return t(`service.priority_${code}`, { defaultValue: titleCase(code) });
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Mirrors `computeSlaChip` in ServicePage: see the file docstring. */
function isBreached(ticket: ServiceTicket, now: number): boolean {
  if (ticket.sla_breached_at) return true;
  if (!ticket.sla_due_at) return false;
  if (TERMINAL.includes(ticket.status)) return false;
  const due = Date.parse(ticket.sla_due_at);
  return !Number.isNaN(due) && due <= now;
}

interface Row {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  ticket: string;
  priority: string;
  status: string;
  origin: string;
  month: string;
  open: number;
  breached: number;
  unassigned: number;
  planned: number;
  hours_open: number;
}

function toRow(
  ticket: ServiceTicket,
  labels: { planned: string; reactive: string },
  t: Translate,
): Row {
  const now = Date.now();
  const live = !TERMINAL.includes(ticket.status);
  const reported = Date.parse(ticket.reported_at);

  // How long the ticket stayed open, which is a fair measure for every ticket
  // rather than only the resolved ones. A live ticket keeps ageing, so a
  // forgotten one looks worse every day; a cancelled one stops when it was
  // cancelled instead of counting as instant.
  const ended = ticket.resolved_at ?? ticket.closed_at ?? (live ? null : ticket.updated_at);
  const endMs = ended ? Date.parse(ended) : now;
  const end = Number.isNaN(endMs) ? now : endMs;
  const fromSchedule = Boolean(ticket.recurring_schedule_id);

  return {
    ticket: ticket.ticket_number,
    priority: priorityLabel(ticket.priority, t),
    status: statusLabel(ticket.status, t),
    origin: fromSchedule ? labels.planned : labels.reactive,
    month: monthKey(ticket.reported_at),
    open: live ? 1 : 0,
    breached: isBreached(ticket, now) ? 1 : 0,
    // Only a live ticket can be waiting for an owner. A closed one with no
    // assignee is history, not a queue someone has to clear.
    unassigned: live && !ticket.assigned_to ? 1 : 0,
    planned: fromSchedule ? 1 : 0,
    hours_open: Number.isNaN(reported) ? 0 : Math.max(0, Math.round((end - reported) / HOUR_MS)),
  };
}

export interface ServiceInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

/**
 * Build the ticket dataset and its built-in charts. Counts and hours only: see
 * the file docstring for why no money appears here.
 */
export function buildServiceInsights(tickets: ServiceTicket[], t: Translate): ServiceInsights {
  const labels = {
    planned: t('service.insights.origin_planned', { defaultValue: 'Planned maintenance' }),
    reactive: t('service.insights.origin_reactive', { defaultValue: 'Reactive callout' }),
  };

  const rows: Row[] = [...tickets]
    .sort((a, b) => Date.parse(a.reported_at) - Date.parse(b.reported_at))
    .map((ticket) => toRow(ticket, labels, t));

  const dataset: InsightDataset = {
    id: 'tickets',
    label: t('service.insights.ds_tickets', { defaultValue: 'Service tickets' }),
    // No money measure, so no currency to format against.
    currency: '',
    fields: [
      { key: 'ticket', label: t('service.insights.f_ticket', { defaultValue: 'Ticket' }), kind: 'dimension' },
      { key: 'priority', label: t('service.insights.f_priority', { defaultValue: 'Priority' }), kind: 'dimension' },
      { key: 'status', label: t('service.insights.f_status', { defaultValue: 'Status' }), kind: 'dimension' },
      { key: 'origin', label: t('service.insights.f_origin', { defaultValue: 'Planned or reactive' }), kind: 'dimension' },
      { key: 'month', label: t('service.insights.f_month', { defaultValue: 'Month reported' }), kind: 'dimension' },
      { key: 'open', label: t('service.insights.f_open', { defaultValue: 'Still open' }), kind: 'measure', format: 'number' },
      { key: 'breached', label: t('service.insights.f_breached', { defaultValue: 'SLA breached' }), kind: 'measure', format: 'number' },
      { key: 'unassigned', label: t('service.insights.f_unassigned', { defaultValue: 'Open with no owner' }), kind: 'measure', format: 'number' },
      { key: 'planned', label: t('service.insights.f_planned', { defaultValue: 'From a recurring schedule' }), kind: 'measure', format: 'number' },
      { key: 'hours_open', label: t('service.insights.f_hours_open', { defaultValue: 'Hours open' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };

  const base = { datasetId: 'tickets', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-open', title: t('service.insights.k_open', { defaultValue: 'Open tickets' }), chart: 'kpi', measure: 'open', agg: 'sum', color: 0 },
    { ...base, id: 'kpi-breached', title: t('service.insights.k_breached', { defaultValue: 'SLA breached' }), chart: 'kpi', measure: 'breached', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-unassigned', title: t('service.insights.k_unassigned', { defaultValue: 'Open with no owner' }), chart: 'kpi', measure: 'unassigned', agg: 'sum', color: 2 },
    { ...base, id: 'kpi-hours', title: t('service.insights.k_hours', { defaultValue: 'Avg hours a ticket stays open' }), chart: 'kpi', measure: 'hours_open', agg: 'avg', color: 5 },
    { ...base, id: 'bar-breached-by-priority', title: t('service.insights.c_breached_by_priority', { defaultValue: 'SLA breaches by priority' }), chart: 'bar', dimension: 'priority', measure: 'breached', agg: 'sum', color: 1 },
    { ...base, id: 'donut-by-origin', title: t('service.insights.c_by_origin', { defaultValue: 'Planned maintenance against reactive callouts' }), chart: 'donut', dimension: 'origin', agg: 'count', color: 4 },
    { ...base, id: 'area-over-time', title: t('service.insights.c_over_time', { defaultValue: 'Tickets raised over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 0 },
  ];

  return { datasets: [dataset], builtins };
}
